"""HTTP routes — mirrors the endpoints consumed by the Go SidecarClient."""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from matter import MatterBridge

log = logging.getLogger("homebase-matter.routes")


class CommissionRequest(BaseModel):
    setup_code: str


class CommandRequest(BaseModel):
    cluster: str
    command: str
    arguments: dict = {}


def register_routes(app: FastAPI):
    def bridge(request: Request) -> MatterBridge:
        return request.app.state.bridge

    @app.get("/health")
    async def health(request: Request):
        ok = bridge(request).healthy()
        status = 200 if ok else 503
        return JSONResponse({"ok": ok}, status_code=status)

    @app.post("/commission")
    async def commission(request: Request, body: CommissionRequest):
        try:
            result = await bridge(request).commission(body.setup_code)
            return result
        except Exception as e:
            log.exception("commission failed")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete("/commission/{node_id}")
    async def decommission(request: Request, node_id: int):
        try:
            await bridge(request).decommission(node_id)
            return {"ok": True}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"node {node_id} not found")
        except Exception as e:
            log.exception("decommission failed")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/devices")
    async def list_devices(request: Request):
        try:
            return await bridge(request).list_devices()
        except Exception as e:
            log.exception("list devices failed")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/devices/{node_id}")
    async def get_device_state(request: Request, node_id: int):
        try:
            return await bridge(request).get_device_state(node_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"node {node_id} not found")
        except Exception as e:
            log.exception("get device state failed")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/devices/{node_id}/command")
    async def send_command(request: Request, node_id: int, body: CommandRequest):
        try:
            result = await bridge(request).send_command(
                node_id=node_id,
                cluster=body.cluster,
                command=body.command,
                arguments=body.arguments,
            )
            return result
        except KeyError:
            raise HTTPException(status_code=404, detail=f"node {node_id} not found")
        except Exception as e:
            log.exception("send command failed")
            raise HTTPException(status_code=500, detail=str(e))
