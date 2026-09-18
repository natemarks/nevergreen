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

systemctl daemon-reload
systemctl enable comfyui.service
systemctl restart comfyui.service
