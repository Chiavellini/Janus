#!/bin/bash
# Launch the Janus box. Billable: THE OPERATOR RUNS THIS after approving the spend.
#   ops/box/launch.sh            # prints the plan
#   ops/box/launch.sh --go       # launches
# Uses what exists in the account: the default VPC, security group janus-box (no ingress), the
# janus-box instance profile (SSM core + /janus/* parameters), Ubuntu 24.04 arm64, c7g.medium
# (~$0.036/h), 20 GB root + 50 GB data (gp3). Access is SSM Session Manager only.
#   ops/box/launch.sh --profile <aws profile> [--go]   # every aws call under that profile
set -euo pipefail
REGION=us-east-1
GO=0; PROFILE=()
while [ $# -gt 0 ]; do
  case "$1" in
    --go) GO=1 ;;
    --profile) shift; PROFILE=(--profile "$1") ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
aws() { command aws ${PROFILE[@]+"${PROFILE[@]}"} "$@"; }
TYPE=${JANUS_BOX_TYPE:-c7g.medium}
SG=${JANUS_BOX_SG:-sg-061f3bb3a68d29f81}
SUBNET=${JANUS_BOX_SUBNET:-subnet-02c7c1eb60f3f8f73}    # us-east-1a
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
