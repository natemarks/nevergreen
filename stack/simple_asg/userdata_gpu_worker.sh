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
