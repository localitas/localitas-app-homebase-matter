"""FastAPI application — implements the REST API expected by the Go SidecarClient."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from auth import Auth
from matter import MatterBridge
from routes import register_routes

log = logging.getLogger("homebase-matter.app")


def create_app(storage: str, api_token: str) -> FastAPI:
    auth = Auth(api_token)
    bridge = MatterBridge(storage=storage)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await bridge.start()
        log.info("Matter bridge started (storage: %s)", storage)
        yield
        await bridge.stop()
        log.info("Matter bridge stopped")

    app = FastAPI(title="homebase-matter", lifespan=lifespan)
    app.state.bridge = bridge
    register_routes(app, auth)
    return app
