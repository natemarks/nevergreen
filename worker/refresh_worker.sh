#!/usr/bin/env bash
# Refresh the containerized explore-a worker (Phase 2, wayfinder ticket
# #29). Shared by two callers:
# - The periodic refresh-worker.timer (no args): pulls the worker image
#   and restarts the container only if a new digest was published. Never
#   touches models -- they only sync once, at instance boot, since they
#   change far less often than the image.
# - `make force_refresh` (--force-models, over SSM): also re-syncs models
#   from S3 first and always restarts, for the rare case new bucket
#   content needs picking up before the container's next natural
#   restart.
set -euo pipefail

# shellcheck source=/dev/null
source /etc/default/explore-worker

CONTAINER_NAME="explore-worker"
MODELS_DIR="/opt/comfyui-data/models"
OUTPUT_DIR="/opt/comfyui-data/output"
FORCE_MODELS=false
if [[ "${1:-}" == "--force-models" ]]; then
  FORCE_MODELS=true
fi

if [[ "${FORCE_MODELS}" == "true" ]]; then
  echo "Force-refresh: re-syncing models from s3://${MODELS_BUCKET}/"
  mkdir -p "${MODELS_DIR}/checkpoints"
  aws s3 sync "s3://${MODELS_BUCKET}/checkpoints/" "${MODELS_DIR}/checkpoints/"
  mkdir -p /usr/share/ollama/.ollama/models
  aws s3 sync "s3://${MODELS_BUCKET}/ollama/" /usr/share/ollama/.ollama/models/
  chown -R ollama:ollama /usr/share/ollama/.ollama
  systemctl restart ollama
fi

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${CONTAINER_IMAGE_URI%%/*}"
docker pull "${CONTAINER_IMAGE_URI}:latest"

new_image_id="$(docker inspect --format '{{.Id}}' "${CONTAINER_IMAGE_URI}:latest")"
running_image_id=""
if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  running_image_id="$(docker inspect --format '{{.Image}}' "${CONTAINER_NAME}")"
fi

if [[ "${FORCE_MODELS}" == "true" || "${new_image_id}" != "${running_image_id}" ]]; then
  echo "Restarting ${CONTAINER_NAME} (new image or forced refresh)"
  docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true
  docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    --gpus all \
    --env-file /etc/default/explore-worker \
    -v "${MODELS_DIR}:/opt/comfyui/models" \
    -v "${OUTPUT_DIR}:/opt/comfyui/output" \
    -p 8188:8188 \
    "${CONTAINER_IMAGE_URI}:latest"
else
  echo "No new image digest; ${CONTAINER_NAME} left running"
fi
