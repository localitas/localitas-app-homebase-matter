# homebase-matter

Matter protocol sidecar for the [Localitas Homebase](https://github.com/localitas/localitas-app-homebase) app.

Part of the [Localitas](https://github.com/localitas) platform — a self-hosted, privacy-first personal computing system.

## What it does

`homebase-matter` is a lightweight Python REST server that bridges the Homebase Go app to the [python-matter-server](https://github.com/home-assistant-libs/python-matter-server) SDK. It handles:

- **Commissioning** — pair new Matter devices using their setup code (QR or manual)
- **Decommissioning** — remove devices from the Matter fabric
- **Device listing** — enumerate all paired devices and their supported clusters
- **Live state** — read current attribute values (on/off, brightness, temperature, lock state, etc.)
- **Commands** — send cluster commands (Toggle, MoveToLevel, SetpointRaiseLower, LockDoor, etc.)

The Homebase app talks to this sidecar via HTTP on `localhost:9222`. If the sidecar is unavailable, Homebase degrades gracefully — the UI still works but device control is disabled.

## Architecture

```
Homebase UI (browser)
      │
      ▼
localitas-app-homebase  (Go, port auto-assigned)
      │  HTTP REST
      ▼
localitas-app-homebase-matter  (Python, port 9222)   ◄── this repo
      │  WebSocket
      ▼
python-matter-server  (subprocess, Unix socket)
      │  Matter over IP / BLE
      ▼
Matter devices (lights, locks, thermostats, …)
```

## API

All endpoints are consumed by the Go `SidecarClient` in `localitas-app-homebase`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check — `200 ok:true` when bridge is ready |
| `POST` | `/commission` | Commission a device by setup code |
| `DELETE` | `/commission/{node_id}` | Remove a device from the fabric |
| `GET` | `/devices` | List all commissioned devices |
| `GET` | `/devices/{node_id}` | Get live cluster state for a device |
| `POST` | `/devices/{node_id}/command` | Send a cluster command to a device |

### Commission request

```json
POST /commission
{ "setup_code": "MT:Y.K9042C00KA0648G00" }
```

```json
{ "node_id": 1, "vendor": "IKEA", "model": "TRADFRI bulb", "clusters": ["OnOff", "LevelControl"] }
```

### Command request

```json
POST /devices/1/command
{ "cluster": "OnOff", "command": "Toggle", "arguments": {} }
```

```json
POST /devices/1/command
{ "cluster": "LevelControl", "command": "MoveToLevel", "arguments": { "level": 128, "transitionTime": 10 } }
```

## Development

### macOS (native, recommended for dev)

Matter commissioning over BLE does not work on macOS. However, already-paired IP devices work fine, and **stub mode** (no real SDK needed) lets you develop the UI without any hardware.

```bash
git clone https://github.com/localitas/localitas-app-homebase-matter.git ~/localitas-app-homebase-matter

# Run natively (auto-creates venv, installs deps)
cd ~/localitas-app-homebase-matter
make dev
```

Or start it automatically as part of the full dev cluster:

```bash
cd ~/localitas
make dev-core   # starts everything including this sidecar on port 9222
```

### Linux (full Matter commissioning)

On Linux the sidecar can commission devices over BLE and mDNS. Run as a privileged container with host networking:

```bash
docker build -t homebase-matter .

docker run -d \
  --name homebase-matter \
  --network host \
  --privileged \
  -v ~/.localitas/homebase/matter:/data/matter \
  homebase-matter
```

`--network=host` is required for mDNS multicast (device discovery). `--privileged` is required for BLE access.

### Stub mode

If `python-matter-server` is not installed, the sidecar runs in **stub mode**: all endpoints respond with plausible fake data. This lets you develop and test the Homebase UI without real Matter hardware or the full SDK build.

```bash
# Install only the lightweight deps (no matter SDK)
pip install fastapi uvicorn pydantic

python main.py --listen :9222
# → WARNING: python-matter-server not installed — running in stub mode
```

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--listen` | `:9222` | TCP address to listen on |
| `--storage` | `~/.localitas/homebase/matter` | Directory for Matter fabric data (node credentials, ACLs) |
| `--log-level` | `info` | Log verbosity: `debug`, `info`, `warning`, `error` |

## Matter cluster support

The following clusters are mapped by name in commands:

| Name | Cluster ID | Typical use |
|------|-----------|-------------|
| `OnOff` | 6 | Lights, switches, outlets |
| `LevelControl` | 8 | Dimmer lights, fans |
| `ColorControl` | 768 | Color bulbs |
| `Thermostat` | 513 | HVAC, climate |
| `DoorLock` | 257 | Smart locks |
| `WindowCovering` | 258 | Blinds, shades |
| `FanControl` | 514 | Fans |

## Testing

```bash
make test
```

Tests run in stub mode — no Matter hardware or SDK required.

## Platform notes

| Feature | macOS | Linux |
|---------|-------|-------|
| IP-connected devices | ✅ | ✅ |
| BLE commissioning | ❌ | ✅ (privileged) |
| mDNS discovery | ✅ | ✅ (host network) |
| Stub mode (no SDK) | ✅ | ✅ |

## License

MIT
