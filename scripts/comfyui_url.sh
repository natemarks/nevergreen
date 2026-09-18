#!/usr/bin/env bash
# Print the URL to reach the gpu_worker ComfyUI instance directly (Phase 0/1).
# Usage: scripts/comfyui_url.sh [app_env] [stack_id] [port]
set -euo pipefail

APP_ENV="${1:-dev}"
STACK_ID="${2:-comfyui}"
PORT="${3:-8188}"

# APP_NAME comes from config/template_defaults.json's "app_name".
APP_NAME="Nevergreen"
STACK_NAME="${APP_NAME}${APP_ENV^}SimpleAsg${STACK_ID^}Stack"

ASG_NAME="$(aws cloudformation describe-stack-resources \
  --stack-name "${STACK_NAME}" \
  --query "StackResources[?ResourceType=='AWS::AutoScaling::AutoScalingGroup'].PhysicalResourceId" \
  --output text)"
if [[ -z "${ASG_NAME}" || "${ASG_NAME}" == "None" ]]; then
  echo "Error: no AutoScalingGroup found in stack ${STACK_NAME}" >&2
  exit 1
fi

INSTANCE_ID="$(aws autoscaling describe-auto-scaling-groups \
  --auto-scaling-group-names "${ASG_NAME}" \
  --query "AutoScalingGroups[0].Instances[0].InstanceId" --output text)"
if [[ -z "${INSTANCE_ID}" || "${INSTANCE_ID}" == "None" ]]; then
  echo "Error: no running instance in ASG ${ASG_NAME} yet" >&2
  exit 1
fi

PUBLIC_IP="$(aws ec2 describe-instances --instance-ids "${INSTANCE_ID}" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text)"
if [[ -z "${PUBLIC_IP}" || "${PUBLIC_IP}" == "None" ]]; then
  echo "Error: instance ${INSTANCE_ID} has no public IP" >&2
  exit 1
fi

echo "http://${PUBLIC_IP}:${PORT}"
