"""Matter bridge — wraps python-matter-server via its WebSocket client API."""
import asyncio
import logging
import os
import subprocess
import sys
from typing import Optional

log = logging.getLogger("homebase-matter.bridge")

# python-matter-server ships both a server process and a client SDK.
# We start the server as a subprocess (listens on a Unix socket) and
# connect to it via the async client library.
try:
    from matter_server.client.client import MatterClient
    from matter_server.client.models.node import MatterNode
    MATTER_AVAILABLE = True
except ImportError:
    MATTER_AVAILABLE = False
    log.warning("python-matter-server not installed — running in stub mode")


class MatterBridge:
    """Manages a python-matter-server child process and its async client."""

    def __init__(self, storage: str):
        self.storage = storage
        self._proc: Optional[subprocess.Popen] = None
        self._client: Optional["MatterClient"] = None
        self._session = None
        self._socket_path: str = os.path.join(storage, "matter-server.sock")
        self._lock = asyncio.Lock()

    async def start(self):
        if not MATTER_AVAILABLE:
            log.warning("Matter server unavailable — all operations will return stubs")
            return

        os.makedirs(self.storage, exist_ok=True)

        # Start the matter-server process (it writes its socket to socket_path)
        cmd = [
            sys.executable, "-m", "matter_server.server",
            "--storage-path", self.storage,
            "--port", "0",  # disable HTTP, use socket only
        ]
        log.info("Starting matter-server: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        await asyncio.sleep(2)  # give server time to bind

        url = f"ws+unix://{self._socket_path}"
        self._client = MatterClient(url, None)
        self._session = await self._client.__aenter__()
        log.info("Connected to matter-server via %s", url)

    async def stop(self):
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # ------------------------------------------------------------------
    # Commission / Decommission
    # ------------------------------------------------------------------

    async def commission(self, setup_code: str) -> dict:
        if not MATTER_AVAILABLE or not self._client:
            return _stub_commission(setup_code)
        node: MatterNode = await self._client.commission_with_code(setup_code)
        return _node_to_commission_response(node)

    async def decommission(self, node_id: int) -> None:
        if not MATTER_AVAILABLE or not self._client:
            return
        await self._client.remove_node(node_id)

    # ------------------------------------------------------------------
    # Device listing / state
    # ------------------------------------------------------------------

    async def list_devices(self) -> list[dict]:
        if not MATTER_AVAILABLE or not self._client:
            return []
        nodes = self._client.get_nodes()
        return [_node_to_device(n) for n in nodes]

    async def get_device_state(self, node_id: int) -> dict:
        if not MATTER_AVAILABLE or not self._client:
            raise KeyError(f"node {node_id} not found")
        node = self._client.get_node(node_id)
        if node is None:
            raise KeyError(f"node {node_id} not found")
        return _node_to_state(node)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def send_command(self, node_id: int, cluster: str, command: str, arguments: dict) -> dict:
        if not MATTER_AVAILABLE or not self._client:
            return {"success": False, "error": "matter server not available"}
        try:
            await self._client.send_device_command(
                node_id=node_id,
                endpoint_id=1,
                cluster_id=_cluster_name_to_id(cluster),
                command_name=command,
                payload=arguments,
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def healthy(self) -> bool:
        if not MATTER_AVAILABLE:
            return True  # stub mode — report healthy so UI works
        return self._client is not None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _node_to_commission_response(node: "MatterNode") -> dict:
    return {
        "node_id": node.node_id,
        "vendor": str(node.node_info.vendor_id) if node.node_info else "unknown",
        "model": str(node.node_info.product_id) if node.node_info else "unknown",
        "clusters": list(node.available_endpoints.keys()) if node.available_endpoints else [],
    }


def _node_to_device(node: "MatterNode") -> dict:
    return {
        "node_id": node.node_id,
        "vendor": str(node.node_info.vendor_id) if node.node_info else "unknown",
        "model": str(node.node_info.product_id) if node.node_info else "unknown",
        "clusters": list(node.available_endpoints.keys()) if node.available_endpoints else [],
        "online": node.available,
    }


def _node_to_state(node: "MatterNode") -> dict:
    clusters: dict = {}
    if node.attributes:
        for endpoint_id, endpoint_attrs in node.attributes.items():
            for cluster_name, attrs in endpoint_attrs.items():
                clusters[cluster_name] = {k: v for k, v in attrs.items()}
    return {
        "node_id": node.node_id,
        "online": node.available,
        "clusters": clusters,
    }


_CLUSTER_IDS = {
    "OnOff": 6,
    "LevelControl": 8,
    "ColorControl": 768,
    "Thermostat": 513,
    "DoorLock": 257,
    "WindowCovering": 258,
    "FanControl": 514,
}


def _cluster_name_to_id(name: str) -> int:
    return _CLUSTER_IDS.get(name, 0)


def _stub_commission(setup_code: str) -> dict:
    """Return a plausible stub response when the SDK is not installed."""
    import hashlib
    node_id = int(hashlib.md5(setup_code.encode()).hexdigest()[:8], 16) % 65536
    return {
        "node_id": node_id,
        "vendor": "stub",
        "model": "stub-device",
        "clusters": ["OnOff", "LevelControl"],
    }
