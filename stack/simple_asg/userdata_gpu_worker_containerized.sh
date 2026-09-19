#!/usr/bin/env bash
# Phase 2 bootstrap for the containerized ComfyUI GPU worker (wayfinder
# ticket #29). Unlike Phase 0/1's userdata_gpu_worker.sh, ComfyUI, its
# custom nodes, and the worker script all live inside the Docker image
# (see worker/Dockerfile, built and pushed via `make build_worker_image`)
# -- this script only prepares the host: grows the filesystem, installs
# Docker, does the one-time model sync from S3, and starts the container.
# A systemd timer then periodically re-checks for a new image digest and
# restarts the container in place -- see refresh_worker.sh, delivered
# onto this instance the same way as explore_worker.py was in Phase 1
# (SimpleAsgStack's extra_files).
set -euxo pipefail

COMFYUI_DATA=/opt/comfyui-data
MODELS_DIR="${COMFYUI_DATA}/models"
OUTPUT_DIR="${COMFYUI_DATA}/output"

# --- Grow the root filesystem to fill the configured EBS volume size ---
# See userdata_gpu_worker.sh for why this is needed and why the root
# device name matters.
ROOT_SOURCE="$(findmnt -n -o SOURCE /)"
ROOT_DISK="/dev/$(lsblk -no PKNAME "${ROOT_SOURCE}")"
ROOT_PART_NUM="${ROOT_SOURCE##*[!0-9]}"
growpart "${ROOT_DISK}" "${ROOT_PART_NUM}" || true # exit 1 = already full size
FS_TYPE="$(findmnt -n -o FSTYPE /)"
if [[ "${FS_TYPE}" == "xfs" ]]; then
  xfs_growfs -d /
else
  resize2fs "${ROOT_SOURCE}"
fi
df -h /

# Ubuntu's own background apt processes (unattended-upgrades, apt-daily)
# can hold the dpkg lock for the first minute or so after boot -- see
# userdata_gpu_worker.sh, where this was confirmed live. Retry instead of
# racing it.
apt_get_retry() {
  for _attempt in $(seq 1 12); do
    if "$@"; then
      return 0
    fi
    echo "apt-get busy (dpkg lock?), retrying in 10s..."
    sleep 10
  done
  return 1
}

apt_get_retry apt-get update -y

# Docker + NVIDIA Container Toolkit: the Deep Learning AMI this project's
# gpu_worker instances use ships both already configured for GPU
# passthrough (`docker run --gpus all`); install only if missing, so this
# script also works on a plain Ubuntu AMI.
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
if ! docker info 2>/dev/null | grep -q "nvidia"; then
  apt_get_retry apt-get install -y nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
fi

# One-time model sync (checkpoints + Ollama's model) -- MODELS_BUCKET
# comes from /etc/default/explore-worker, written before this script runs
# (see stack/simple_asg.py's extra_files). Only at boot: models change
# far less often than the worker image, and `make force_refresh` handles
# the rare case a running instance needs new bucket content sooner --
# see refresh_worker.sh.
# shellcheck source=/dev/null
source /etc/default/explore-worker
mkdir -p "${MODELS_DIR}/checkpoints" "${OUTPUT_DIR}"
aws s3 sync "s3://${MODELS_BUCKET}/checkpoints/" "${MODELS_DIR}/checkpoints/"

curl -fsSL https://ollama.com/install.sh | sh
mkdir -p /usr/share/ollama/.ollama/models
aws s3 sync "s3://${MODELS_BUCKET}/ollama/" /usr/share/ollama/.ollama/models/
chown -R ollama:ollama /usr/share/ollama/.ollama
systemctl enable ollama
systemctl restart ollama

# refresh_worker.sh is delivered onto this instance via extra_files (the
# same tested-repo-file mechanism as explore_worker.py in Phase 1) at
# /opt/comfyui/bin/refresh_worker.sh -- see config/inventory.py.
chmod +x /opt/comfyui/bin/refresh_worker.sh

# Initial pull + start: refresh_worker.sh always starts a container when
# none is running yet, since there's nothing to compare image digests
# against.
/opt/comfyui/bin/refresh_worker.sh

cat >/etc/systemd/system/refresh-worker.service <<UNIT
[Unit]
Description=Pull the worker image and restart the container if a new digest was published

[Service]
Type=oneshot
ExecStart=/opt/comfyui/bin/refresh_worker.sh
UNIT

cat >/etc/systemd/system/refresh-worker.timer <<UNIT
[Unit]
Description=Periodically check for a new worker image

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now refresh-worker.timer
