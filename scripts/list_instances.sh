#!/usr/bin/env bash
# List EC2 instances in the current AWS CLI region/profile: name, instance
# id, and public IP address.
set -euo pipefail

aws ec2 describe-instances \
  --query "Reservations[].Instances[].{Name: (Tags[?Key=='Name'].Value | [0]), InstanceId: InstanceId, PublicIP: PublicIpAddress, State: State.Name}" \
  --output table
