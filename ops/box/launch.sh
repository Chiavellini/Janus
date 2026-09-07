#!/bin/bash
# Launch the Janus box. Billable: THE OPERATOR RUNS THIS after approving the spend.
#   ops/box/launch.sh            # prints the plan
#   ops/box/launch.sh --go       # launches (us-east-1 unless JANUS_BOX_REGION / --region says otherwise)
# Uses what exists in the account: the default VPC, security group janus-box (no ingress), the
# janus-box instance profile (SSM core + /janus/* parameters), Ubuntu 24.04 arm64, c7g.medium
# (~$0.036/h), 20 GB root + 50 GB data (gp3). Access is SSM Session Manager only.
#   ops/box/launch.sh --profile <aws profile> [--go]   # every aws call under that profile
#   JANUS_BOX_REGION=mx-central-1 ops/box/launch.sh --go   # the Mexico box (2026-09-07: Polymarket
#       geoblocks order entry from AWS Virginia; the CLOB accepts orders from Mexico, where the
#       proofs ran). Any region: the default VPC's subnet in <region>a and a `janus-box` security
#       group (no ingress) are resolved or created there; the AMI comes from the region's public
#       SSM parameter; the instance profile is global. The /janus/* parameters must already exist in
#       that region (ops/box/copy_params.sh) and infra/iam/*.json must name it.
set -euo pipefail
REGION=${JANUS_BOX_REGION:-us-east-1}
GO=0; PROFILE=()
while [ $# -gt 0 ]; do
  case "$1" in
    --go) GO=1 ;;
    --profile) shift; PROFILE=(--profile "$1") ;;
    --region) shift; REGION=$1 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
aws() { command aws ${PROFILE[@]+"${PROFILE[@]}"} "$@"; }
TYPE=${JANUS_BOX_TYPE:-c7g.medium}
if [ "$REGION" = us-east-1 ]; then
  SG=${JANUS_BOX_SG:-sg-061f3bb3a68d29f81}
  SUBNET=${JANUS_BOX_SUBNET:-subnet-02c7c1eb60f3f8f73}    # us-east-1a
else
  VPC=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
  case "$VPC" in vpc-*) ;; *) echo "no default VPC in $REGION: aws ec2 create-default-vpc --region $REGION (the operator's)" >&2; exit 2 ;; esac
  SUBNET=${JANUS_BOX_SUBNET:-$(aws ec2 describe-subnets --region "$REGION" --filters Name=vpc-id,Values="$VPC" Name=availability-zone,Values="${REGION}a" --query 'Subnets[0].SubnetId' --output text)}
  case "$SUBNET" in subnet-*) ;; *) echo "no subnet in ${REGION}a of $VPC" >&2; exit 2 ;; esac
  SG=${JANUS_BOX_SG:-$(aws ec2 describe-security-groups --region "$REGION" --filters Name=vpc-id,Values="$VPC" Name=group-name,Values=janus-box --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)}
  case "$SG" in
    sg-*) ;;
    *) if [ "$GO" = 1 ]; then
         SG=$(aws ec2 create-security-group --region "$REGION" --vpc-id "$VPC" --group-name janus-box --description "Janus box: no ingress, SSM only" --query GroupId --output text)
         aws ec2 create-tags --region "$REGION" --resources "$SG" --tags Key=Project,Value=janus >/dev/null
       else
         SG="(janus-box, created on --go)"
       fi ;;
  esac
fi
# The AMI id: resolved from the public SSM parameter, or given as JANUS_BOX_AMI when the launching
# principal (the janus-agent role) may run instances but not read public parameters.
AMI=${JANUS_BOX_AMI:-$(aws ssm get-parameters --region $REGION --names /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id --query "Parameters[0].Value" --output text 2>/dev/null || true)}
case "$AMI" in ami-*) ;; *) echo "no AMI: the SSM lookup failed (set JANUS_BOX_AMI=ami-… when the launching principal cannot read public parameters)" >&2; exit 2 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
echo "plan: $TYPE in $REGION, ami $AMI, subnet $SUBNET, sg $SG, profile janus-box, 20+50 GB gp3, tags Project=janus Name=janus-box${PROFILE:+, aws profile ${PROFILE[1]}}"
[ "$GO" = 1 ] || { echo "dry run; pass --go to launch"; exit 0; }
aws ec2 run-instances --region $REGION --image-id "$AMI" --instance-type "$TYPE" \
  --subnet-id "$SUBNET" --security-group-ids "$SG" --iam-instance-profile Name=janus-box \
  --associate-public-ip-address --user-data "file://$HERE/user-data.sh" \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3","DeleteOnTermination":true}},{"DeviceName":"/dev/sdf","Ebs":{"VolumeSize":50,"VolumeType":"gp3","DeleteOnTermination":false}}]' \
  --metadata-options HttpTokens=required \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Project,Value=janus},{Key=Name,Value=janus-box}]' 'ResourceType=volume,Tags=[{Key=Project,Value=janus}]' \
  --query "Instances[0].{id:InstanceId,az:Placement.AvailabilityZone,type:InstanceType}" --output table
echo "stop the bill any time: aws ec2 stop-instances --region $REGION --instance-ids <id>"
