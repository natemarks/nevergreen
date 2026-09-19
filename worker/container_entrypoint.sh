#!/usr/bin/env bash
# Container entrypoint: starts ComfyUI in the background, waits for it to
# accept connections, then execs explore_worker.py as the container's
# main (foreground) process -- so `docker stop` signals the worker
# directly. Both processes read the same EnvironmentFile-style env vars
# passed to `docker run --env-file` (QUEUE_URL, OUTPUT_BUCKET, etc.).
set -euo pipefail

cd "${COMFYUI_HOME}"
./venv/bin/python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header &

for _attempt in $(seq 1 60); do
  if (exec 3<>/dev/tcp/127.0.0.1/8188) 2>/dev/null; then
    exec 3<&- 3>&-
    break
  fi
  sleep 5
done

exec ./venv/bin/python3 explore_worker.py
