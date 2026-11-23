"""Command-line entry points: `newcad-engine` (HTTP API + MCP) and `newcad-mcp` (MCP over stdio)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys


def _free_port(host: str) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def engine_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="NewCAD engine: REST + WebSocket + MCP on one port")
    ap.add_argument("--host", default=os.environ.get("NEWCAD_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("NEWCAD_PORT", "0")), help="0 picks a free port")
    ap.add_argument("--token", default=os.environ.get("NEWCAD_TOKEN", ""), help="default: random per launch")
    ap.add_argument("--demo", action="store_true", help="create a demo project if there are none")
    ap.add_argument("--worker", action="store_true",
                    help="compute-node mode: run simulation jobs for other NewCAD engines (pair it under Settings → Compute)")
    ap.add_argument("--tls-cert", default=os.environ.get("NEWCAD_TLS_CERT"), help="serve HTTPS with this certificate (PEM)")
    ap.add_argument("--tls-key", default=os.environ.get("NEWCAD_TLS_KEY"), help="private key for --tls-cert")
    ap.add_argument("--sim-slots", type=int, default=int(os.environ.get("NEWCAD_SIM_SLOTS", "0")) or None,
                    help="simulation jobs that run at the same time (default 1)")
    args = ap.parse_args(argv)
    if args.sim_slots:
        os.environ["NEWCAD_SIM_SLOTS"] = str(args.sim_slots)

    import uvicorn

    from .api.app import create_app
    from .config import Config
    from .core import Engine

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = Config(host=args.host, token=args.token).ensure()
    port = args.port or _free_port(args.host)
    engine = Engine(cfg)
    if args.demo and not engine.store.list():
        engine.store.create("Generator mount", "Hold a 4 kg generator coaxial with a turbine shaft and carry its weight into the rig frame.", "demo")
    scheme = "https" if args.tls_cert else "http"
    if args.worker:
        from .jobs.devices import describe_local
        d = describe_local()
        missing = [k for k, v in d["solvers"].items() if not v]
        print(f"NewCAD compute node on {scheme}://{args.host}:{port}: {d['cpu']['performance_cores']} cores, "
              f"{len(d['gpus'])} CUDA GPU(s), solvers {d['solvers']}" + (f" (missing: {', '.join(missing)})" if missing else ""), flush=True)
        print(f"Pair it in NewCAD under Settings → Compute with this token: {cfg.token}", flush=True)
    else:
        cfg.write_runtime(port)
    # one machine-readable line so the Tauri shell (or a script) can pick up port and token
    print(f"NEWCAD_ENGINE url={scheme}://{args.host}:{port} token={cfg.token}", flush=True)
    uvicorn.run(create_app(engine), host=args.host, port=port, log_level="warning", ws="websockets-sansio",
                ssl_certfile=args.tls_cert, ssl_keyfile=args.tls_key)


def mcp_main(argv: list[str] | None = None) -> None:
    """MCP over stdio for desktop agents (Claude Desktop, Claude Code, Cursor).

    Runs its own engine in this process on the same project folder
    (NEWCAD_HOME, default ~/.newcad). A running NewCAD app notices the commits.
    """
    ap = argparse.ArgumentParser(description="NewCAD MCP server over stdio")
    ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    os.environ.setdefault("NEWCAD_WORKERS", "2")

    from .config import Config
    from .core import Engine

    async def run() -> None:
        engine = Engine(Config())
        await engine.start()
        try:
            await engine.mcp.run_stdio_async()
        finally:
            await engine.stop()

    asyncio.run(run())
