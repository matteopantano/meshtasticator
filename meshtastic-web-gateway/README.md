# RAK4630 Web UI Gateway

A lightweight FastAPI web application that runs on a Linux VM, talks to a USB-connected Meshtastic node, and reuses the repository's existing signed Meshtastic command flow.

## Architecture

Phone / Tablet → HTTP → FastAPI web app → existing Meshtastic command implementation → RAK4630 over USB/serial → LoRa

This project does not add MQTT, a new Meshtastic protocol, or a second command format. It wraps the existing signed `target` + `action` + `seq` + `sig` mechanism already implemented in [meshtasticd-config/send_control_cmd.py](../meshtasticd-config/send_control_cmd.py).

## Project Layout

- [app/main.py](app/main.py): FastAPI app factory and static file mounting
- [app/api.py](app/api.py): `/api/status`, `/api/commands`, `/api/commands` POST
- [app/commands/registry.py](app/commands/registry.py): UI command registry mapped to existing target/action pairs
- [app/commands/service.py](app/commands/service.py): command validation, dispatch, last-status tracking
- [app/meshtastic/adapter.py](app/meshtastic/adapter.py): adapter that calls the existing sender implementation
- [app/static/index.html](app/static/index.html), [app/static/app.js](app/static/app.js), [app/static/style.css](app/static/style.css): responsive UI
- [tests/](tests/): API, registry, adapter, and mock-mode tests

## Installation

1. Create a Python environment.
2. Install dependencies:

   `pip install -r meshtastic-web-gateway/requirements.txt`

3. Choose your config source:

   - Recommended: keep shared values in the repository root [.env](../.env)
   - Optional: create `meshtastic-web-gateway/.env` only for gateway-specific overrides

4. If you want a local gateway override file, copy the template:

   `cp meshtastic-web-gateway/.env.example meshtastic-web-gateway/.env`

5. Edit the values, especially:
   - `MESHTASTIC_DEVICE`
   - `CONTROL_SECRET`
   - `TARGET_DEVICE_ID`

## Keeping configuration in sync

The gateway already supports a single-source-of-truth setup:

- [meshtastic-web-gateway/app/config.py](app/config.py) loads `meshtastic-web-gateway/.env` first, then falls back to the repository root [.env](../.env)
- [meshtastic-web-gateway/docker-compose.yml](docker-compose.yml) now passes both `../.env` and `.env` into the container, with the local gateway `.env` overriding shared values only when needed

Recommended usage:

- Put shared values in the repository root [.env](../.env): `CONTROL_SECRET`, `LORA_REGION`, Wi-Fi settings, common node IDs
- Put gateway-only values in `meshtastic-web-gateway/.env`: `MESHTASTIC_DEVICE`, `WEB_PORT`, `APP_TITLE`, optional `COMMANDS_JSON`, optional `TARGET_DEVICE_ID`
- If the same variable exists in both files, the gateway-local `.env` wins

This avoids having to manually keep two full `.env` files identical.

## Connecting the RAK4630

1. Connect the Meshtastic node to the Linux VM with USB pass-through enabled.
2. Find the serial device:
   - `ls /dev/ttyACM* /dev/ttyUSB*`
   - `dmesg | tail`
3. Set `MESHTASTIC_DEVICE` in [meshtastic-web-gateway/.env.example](.env.example) / `.env`, for example `/dev/ttyACM0`.

## Starting the web application

From the repository root:

`uvicorn app.main:app --app-dir meshtastic-web-gateway --host 0.0.0.0 --port 8000`

Then open `http://<vm-ip>:8000`.

## API

### `GET /api/status`

Returns connection state, last command, and available commands.

### `GET /api/commands`

Returns the configured UI buttons.

### `POST /api/commands`

Example payload:

`{"command":"ON"}`

The backend validates the command, maps it to the existing Meshtastic target/action structure, and calls the existing sender implementation.

## Mock mode

Set `MOCK_MESHTASTIC=true` to run the UI without hardware. Commands are logged and reported as `mock-sent`.

## Docker deployment

Build and run from the repository root so the existing sender script is included in the build context:

1. Copy [meshtastic-web-gateway/.env.example](.env.example) to `meshtastic-web-gateway/.env`.
2. Adjust `MESHTASTIC_DEVICE`, then run:

   `docker compose -f meshtastic-web-gateway/docker-compose.yml up --build`

The compose file maps the configured serial device into the container.

## Adding an existing command as a UI button

Use `COMMANDS_JSON` in `.env` to define application-level button names while still using the existing target/action protocol.

Example:

`COMMANDS_JSON=[{"command":"OPEN_GATE","label":"Open Gate","target":"gate-relay","action":"ON","variant":"success"},{"command":"CLOSE_GATE","label":"Close Gate","target":"gate-relay","action":"OFF","variant":"danger"}]`

This does not change the radio payload format. It only changes which existing target/action pair the UI triggers.

## Troubleshooting

- If `/api/status` reports disconnected, verify `MESHTASTIC_DEVICE` and USB pass-through.
- If the node has no Wi-Fi, that is fine for this app; USB/serial is the transport.
- If commands time out, the packet may still have been sent; check the remote gateway node and radio path.
- Never log or commit real secrets.
