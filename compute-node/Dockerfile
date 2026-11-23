# NewCAD compute node: the engine in worker mode on a Linux machine (with or without an NVIDIA GPU).
#
#   docker build -t newcad-node -f compute-node/Dockerfile .
#   docker run --gpus all -p 8765:8765 -e NEWCAD_TOKEN=$(openssl rand -hex 24) newcad-node
#
# Then add it in the app under Settings → Compute with its URL and the token.
# Put it behind HTTPS (a reverse proxy, or NEWCAD_TLS_CERT/NEWCAD_TLS_KEY) when it is reached over a network
# you don't trust. FEM and single motion runs use the CPU; motion parameter sweeps use the GPU (MuJoCo Warp).
FROM nvidia/cuda:12.6.3-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 NEWCAD_HOME=/data
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl calculix-ccx \
        libglu1-mesa libxcursor1 libxinerama1 libxft2 libxrender1 libgl1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /opt/newcad/engine
COPY engine/pyproject.toml engine/README.md* ./
COPY engine/newcad_engine ./newcad_engine
# the cuda extra adds MuJoCo Warp: motion sweeps run as parallel worlds on the GPU
RUN uv venv --python 3.12 /opt/venv && VIRTUAL_ENV=/opt/venv uv pip install --no-cache ".[cuda]"
ENV PATH=/opt/venv/bin:$PATH

RUN useradd --create-home --uid 1000 newcad && mkdir -p /data && chown newcad /data
USER newcad
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://127.0.0.1:8765/api/health || exit 1
ENTRYPOINT ["newcad-engine", "--worker", "--host", "0.0.0.0", "--port", "8765"]
