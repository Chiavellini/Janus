#!/usr/bin/env bash
# Copy the eight /janus/* SSM parameters from one region to another, type for type. THE OPERATOR
# RUNS THIS: the six SecureStrings are their credentials (read with decryption here, written with
# the destination region's default SSM key). Nothing is printed but the names.
#   bash ops/box/copy_params.sh mx-central-1              # from us-east-1, dry run: lists what would move
#   bash ops/box/copy_params.sh mx-central-1 --go
#   JANUS_BOX_SOURCE_REGION=us-east-1
set -euo pipefail
TO=${1:?destination region, e.g. mx-central-1}
GO=0; [ "${2:-}" = "--go" ] && GO=1
FROM=${JANUS_BOX_SOURCE_REGION:-us-east-1}
NAMES=$(aws ssm describe-parameters --region "$FROM" --parameter-filters Key=Name,Option=BeginsWith,Values=/janus/ --query 'Parameters[].Name' --output text)
for n in $NAMES; do
  type=$(aws ssm describe-parameters --region "$FROM" --parameter-filters "Key=Name,Values=$n" --query 'Parameters[0].Type' --output text)
  echo "$n ($type) $FROM -> $TO"
  [ $GO = 1 ] || continue
  # the value never touches a file or the terminal: straight from one call into the other
  aws ssm put-parameter --region "$TO" --overwrite --name "$n" --type "$type" \
    --value "$(aws ssm get-parameter --region "$FROM" --name "$n" --with-decryption --query Parameter.Value --output text)" >/dev/null
done
[ $GO = 1 ] && echo "copied; verify: aws ssm describe-parameters --region $TO --parameter-filters Key=Name,Option=BeginsWith,Values=/janus/ --query 'Parameters[].Name'" || echo "dry run; pass --go to copy"
