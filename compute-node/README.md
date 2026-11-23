# Compute node

A compute node is a NewCAD engine started with `--worker` on another machine, usually a Linux box with an
NVIDIA GPU or many cores. The app sends simulation jobs to it as a *remote compute target*: the job's
inputs (part BREPs and the resolved study) go up as a tar.gz, progress is polled, and results come back
the same way. The node runs exactly the same pipeline as the local target, so results match.

## Run it

With Docker (Linux, optional NVIDIA Container Toolkit for `--gpus all`):

```sh
docker build -t newcad-node -f compute-node/Dockerfile .
docker run -d --gpus all -p 8765:8765 -e NEWCAD_TOKEN=<long random token> -v newcad-node:/data newcad-node
```

Without Docker, on any machine with CalculiX (`ccx`) on the PATH:

```sh
cd engine && uv run newcad-engine --worker --host 0.0.0.0 --port 8765 --token <long random token>
```

`--sim-slots N` runs N jobs at once (threads are split between them). `--tls-cert` and `--tls-key` serve
HTTPS directly; otherwise put the node behind a reverse proxy that terminates TLS.

## Pair it

In the app: Check tab → Compute → Add compute node, with the node's URL and token. Or over REST:

```sh
curl -X POST http://127.0.0.1:<port>/api/targets -H "Authorization: Bearer <engine token>" \
     -H 'Content-Type: application/json' -d '{"name": "Lab GPU", "url": "https://node:8765", "token": "<node token>"}'
```

The scheduler then picks a target per job: CPU-only solvers (Gmsh, CalculiX) stay on this computer unless
it is busy; solvers that prefer CUDA go to a node with a GPU. A study can pin a target in its YAML
(`target: lab-gpu`). If a node drops out mid-job, the job moves to another target.
