# Computer-use sandbox (Phase E) — in-container virtual desktop + action shim.
#
# The host GEODE harness (computer_use_env=sandbox) POSTs actions to this
# container's shim_server.py, which drives the container's own Xvfb display via
# pyautogui. The host never touches a display — only HTTP. This is the frontier
# "in-container shim" model (E2B / trycua), the only one that works regardless
# of the host OS (incl. macOS, where Docker is a Linux VM that cannot reach the
# host display).
#
# unverified — live test required: not built/run in CI (no Docker/Xvfb there).
# Build + run on a Linux Docker host:
#   docker build -t geode-cu-sandbox docker/computer-use-sandbox/
#   docker run --rm -p 8787:8787 geode-cu-sandbox
# then on the host: GEODE_COMPUTER_USE_ENV=sandbox \
#   GEODE_COMPUTER_USE_SANDBOX_URL=http://127.0.0.1:8787 geode

FROM python:3.12-slim

# Xvfb (virtual X display) + a minimal WM + the libs pyautogui/Pillow need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11-utils fluxbox scrot xdotool \
        libxtst6 libpng16-16 libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/geode
# Install only the [desktop] runtime deps the harness needs; put `core` on
# PYTHONPATH rather than `pip install -e .` (which would require the whole
# package's readme + plugins + pydantic stack — overkill for the shim).
RUN pip install --no-cache-dir "pyautogui>=0.9.54" "Pillow>=10.0.0" "pydantic>=2" "pydantic-settings>=2"
COPY core ./core
COPY docker/computer-use-sandbox/shim_server.py ./shim_server.py

ENV PYTHONPATH=/opt/geode
ENV DISPLAY=:99
ENV GEODE_COMPUTER_USE_ENV=host
EXPOSE 8787

# Start Xvfb on :99, a WM, then the shim server (host-mode inside the container).
CMD Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 & \
    sleep 1 && fluxbox >/tmp/wm.log 2>&1 & \
    python shim_server.py
