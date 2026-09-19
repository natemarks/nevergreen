# Phase 2 containerized worker (wayfinder ticket #29): ComfyUI + the same
# custom nodes userdata_gpu_worker.sh (Phase 0/1) installed directly on the
# host, plus explore_worker.py, all baked into one image. Built and pushed
# to ECR outside `cdk deploy` -- see config/build_worker_image.py.
#
# Model checkpoints and Ollama's model are NOT baked in -- they're synced
# from the models S3 bucket onto a host directory that gets bind-mounted
# in at `docker run` time (see stack/simple_asg/userdata_gpu_worker_containerized.sh),
# so a new image push never needs to re-ship multi-GB model weights.
#
# GPU access itself can't be containerized: the host still needs the
# NVIDIA kernel driver and the NVIDIA Container Toolkit (`docker run
# --gpus all`) -- both already present on the Deep Learning AMI this
# project's gpu_worker instances use.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV COMFYUI_HOME=/opt/comfyui

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    git python3 python3-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/comfyanonymous/ComfyUI "${COMFYUI_HOME}"

WORKDIR ${COMFYUI_HOME}
RUN python3 -m venv venv \
    && ./venv/bin/pip install --upgrade pip \
    && ./venv/bin/pip install -r requirements.txt \
    && ./venv/bin/pip install boto3==1.43.92 requests==2.34.2

# Same custom nodes, same order, as userdata_gpu_worker.sh -- keep both in
# sync if this list changes.
RUN mkdir -p custom_nodes && cd custom_nodes && \
    for repo in \
      https://github.com/ltdrdata/ComfyUI-Impact-Pack \
      https://github.com/cubiq/ComfyUI_IPAdapter_plus \
      https://github.com/Fannovel16/comfyui_controlnet_aux \
      https://github.com/glibsonoran/Plush-for-ComfyUI \
      https://github.com/BadCafeCode/masquerade-nodes-comfyui ; do \
        dir="$(basename "${repo}")" && \
        git clone "${repo}" "${dir}" && \
        if [ -f "${dir}/requirements.txt" ]; then \
          "${COMFYUI_HOME}/venv/bin/pip" install -r "${dir}/requirements.txt" || true ; \
        fi ; \
    done

COPY worker/explore_worker.py "${COMFYUI_HOME}/explore_worker.py"
COPY workflows/txt2img-example.json "${COMFYUI_HOME}/workflows/txt2img-example.json"
COPY worker/container_entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Bind-mounted from the host at `docker run` time -- see the containerized
# userdata script.
VOLUME ["/opt/comfyui/models", "/opt/comfyui/output"]

EXPOSE 8188

ENTRYPOINT ["/entrypoint.sh"]
