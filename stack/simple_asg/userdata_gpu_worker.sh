#!/usr/bin/env bash
# Phase 0 bootstrap for the ComfyUI GPU worker (research/aws-infrastructure.md).
#
# Best-effort prototype install: clones ComfyUI + the custom nodes the
# research calls out, then runs ComfyUI as a systemd service listening on
# 0.0.0.0:8188. Relies on the Deep Learning AMI's pre-installed NVIDIA
# drivers/CUDA/PyTorch; if a custom node's own requirements.txt pulls in a
# CPU-only torch build, reinstall the matching CUDA torch wheel by hand over
# SSM before relying on GPU generation.
#
# Models are NOT downloaded here (Phase 0 decision: manual download over an
# SSM session) — see the Phase 0 ticket's UAT steps.
#
# Phase 1 addition: installs Ollama (for seed-prompt expansion) and the
# explore-a-queue worker (worker/explore_worker.py, embedded onto the
# instance via SimpleAsgStack's `extra_files` mechanism -- see
# stack/simple_asg.py -- so the tested repo file is what runs here, not a
# hand-duplicated copy) as a systemd service.
set -euxo pipefail

COMFYUI_HOME=/opt/comfyui
COMFYUI_USER=ubuntu

# --- Grow the root filesystem to fill the configured EBS volume size ---
# Enlarging the EBS volume at launch only grows the block device; the
# partition and filesystem inside it must be extended separately -- this is
# universal EC2/EBS behavior, not something CloudFormation/CDK can do for
# you. Confirmed via `lsblk` on this AMI: root (nvme0n1p1) is a plain
# partition, not LVM (the AMI's LVM volume group is only the separate
# ephemeral instance-store disk at /opt/dlami/nvme). Root device name must
# match the AMI's actual RootDeviceName (`aws ec2 describe-images --query
# Images[0].RootDeviceName`) or the configured EBS volume attaches as an
# extra, unused disk instead of becoming the root volume -- this is why
# root_block_device_name is "/dev/sda1", not the more common "/dev/xvda".
# See https://docs.aws.amazon.com/ebs/latest/userguide/recognize-expanded-volume-linux.html
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

apt-get update -y
apt-get install -y git python3-venv

if [[ ! -d "${COMFYUI_HOME}" ]]; then
  git clone https://github.com/comfyanonymous/ComfyUI "${COMFYUI_HOME}"
fi

cd "${COMFYUI_HOME}"
python3 -m venv venv
# shellcheck source=/dev/null
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# explore_worker.py's own runtime dependencies (kept in step with
# requirements.txt at the repo root) -- installed into the same venv so one
# interpreter runs both ComfyUI and the worker.
pip install boto3==1.43.92 requests==2.34.2

mkdir -p custom_nodes
cd custom_nodes
declare -a CUSTOM_NODES=(
  "https://github.com/ltdrdata/ComfyUI-Impact-Pack"
  "https://github.com/cubiq/ComfyUI_IPAdapter_plus"
  "https://github.com/Fannovel16/comfyui_controlnet_aux"
  "https://github.com/glibsonoran/Plush-for-ComfyUI"
  "https://github.com/BadCafeCode/masquerade-nodes-comfyui"
)
for repo in "${CUSTOM_NODES[@]}"; do
  dir="$(basename "${repo}")"
  if [[ ! -d "${dir}" ]]; then
    git clone "${repo}"
  fi
  if [[ -f "${dir}/requirements.txt" ]]; then
    "${COMFYUI_HOME}/venv/bin/pip" install -r "${dir}/requirements.txt" || true
  fi
done

chown -R "${COMFYUI_USER}:${COMFYUI_USER}" "${COMFYUI_HOME}"

# Ollama expands each job's seed_prompt into a batch of SD-style prompt
# variants (research/local-llm-image-generation.md's Advanced Prompt
# Enhancer pattern). The official installer sets up its own
# ollama.service; pulling the model here blocks boot completion until the
# download finishes, which is acceptable for this prototype instance.
curl -fsSL https://ollama.com/install.sh | sh
systemctl enable --now ollama
OLLAMA_MODEL="llama3.1"
for _attempt in $(seq 1 10); do
  if ollama pull "${OLLAMA_MODEL}"; then
    break
  fi
  sleep 5
done

cat >/etc/systemd/system/comfyui.service <<UNIT
[Unit]
Description=ComfyUI
After=network.target

[Service]
Type=simple
User=${COMFYUI_USER}
WorkingDirectory=${COMFYUI_HOME}
ExecStart=${COMFYUI_HOME}/venv/bin/python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/explore-worker.service <<UNIT
[Unit]
Description=Explore-A queue worker
After=network.target comfyui.service ollama.service
Wants=comfyui.service ollama.service

[Service]
Type=simple
User=${COMFYUI_USER}
WorkingDirectory=${COMFYUI_HOME}
EnvironmentFile=/etc/default/explore-worker
ExecStart=${COMFYUI_HOME}/venv/bin/python3 ${COMFYUI_HOME}/explore_worker.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable comfyui.service explore-worker.service
systemctl restart comfyui.service
systemctl restart explore-worker.service
