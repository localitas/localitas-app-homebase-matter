#!/usr/bin/env python3
"""homebase-matter — Matter protocol sidecar for Localitas Homebase."""
import argparse
import logging
import signal
import sys

from app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("homebase-matter")


def main():
    parser = argparse.ArgumentParser(prog="homebase-matter")
    parser.add_argument("--listen", default=":9222", help="listen address (default :9222)")
    parser.add_argument("--storage", default="", help="path to Matter fabric storage dir (default ~/.localitas/homebase/matter)")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    parser.add_argument("--token", default="", help="core API token to verify callers with (default $LOCALITAS_API_TOKEN)")
    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    host = "0.0.0.0"
    port = 9222
    listen = args.listen.lstrip(":")
    if ":" in listen:
        parts = listen.rsplit(":", 1)
        host = parts[0] or "0.0.0.0"
        port = int(parts[1])
    elif listen:
        port = int(listen)

    import os
    storage = args.storage or os.path.expanduser("~/.localitas/homebase/matter")
    os.makedirs(storage, exist_ok=True)

    token = args.token or os.environ.get("LOCALITAS_API_TOKEN", "")
    if not token:
        log.error("no API token: pass --token or set LOCALITAS_API_TOKEN; refusing to serve without authentication")
        sys.exit(1)
    app = create_app(storage=storage, api_token=token)

    def _shutdown(sig, frame):
        log.info("shutting down")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    import uvicorn
    log.info("homebase-matter sidecar listening on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
