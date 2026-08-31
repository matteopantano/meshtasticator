#!/usr/bin/env python3
"""
Simulated RF TCP Cross-Routing Bridge

`meshtasticd -s` (SimRadio) has no radio-layer networking of its own - each
simulated node only loops transmitted packets back out over its own
phone/API TCP connection, framed as a SIMULATOR_APP (portnum 69) packet.
To let two separate `meshtasticd -s` Docker containers (RX and TX) exchange
simulated LoRa RF traffic, this bridge connects to each node's TCP mux port
(exposed by `proxy.py` on port 4404, NOT the meshtasticd :4403 port directly,
which only accepts a single client connection that is already held by the
corresponding `ws-proxy-*` container) and cross-relays any FromRadio packet
with `decoded.portnum == SIMULATOR_APP` from one node into a ToRadio packet
sent to the other node.

Env vars (all overridable, defaults match docker-compose.yaml service names):
  RX_MUX_HOST=ws-proxy-rx   RX_MUX_PORT=4404
  TX_MUX_HOST=ws-proxy-tx   TX_MUX_PORT=4404
"""

import os
import time
import asyncio

from meshtastic.protobuf import mesh_pb2, portnums_pb2

START1 = 0x94
START2 = 0xC3
HEADER_LEN = 4

RX_MUX_HOST = os.environ.get("RX_MUX_HOST", "ws-proxy-rx")
RX_MUX_PORT = int(os.environ.get("RX_MUX_PORT", "4404"))
TX_MUX_HOST = os.environ.get("TX_MUX_HOST", "ws-proxy-tx")
TX_MUX_PORT = int(os.environ.get("TX_MUX_PORT", "4404"))

# How long to remember a relayed (from, id) pair before it can be relayed
# again in the same direction (simple anti-loop cache, not full mesh routing -
# the discrete-event simulator in lib/ already does real RF simulation, this
# bridge only needs to be a dumb store-and-forward relay for the two-node
# Docker demo).
SEEN_TTL_SECONDS = 10.0


def frame(payload: bytes) -> bytes:
    """Wrap a serialized protobuf payload with the standard stream header."""
    msg_len = len(payload)
    header = bytes([START1, START2, (msg_len >> 8) & 0xFF, msg_len & 0xFF])
    return header + payload


class RecentlySeen:
    """Tracks (from, id) tuples relayed in one direction, expiring old ones."""

    def __init__(self, ttl: float = SEEN_TTL_SECONDS):
        self.ttl = ttl
        self._entries = {}

    def seen(self, key) -> bool:
        self._expire()
        return key in self._entries

    def add(self, key) -> None:
        self._entries[key] = time.monotonic()

    def _expire(self) -> None:
        now = time.monotonic()
        expired = [k for k, ts in self._entries.items() if now - ts > self.ttl]
        for k in expired:
            del self._entries[k]


class MuxConnection:
    """Long-lived reconnecting TCP client handle to a ws-proxy mux port (4404)."""

    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.host = host
        self.port = port
        self.writer = None

    async def send_packet(self, packet):
        """Frame a MeshPacket into a ToRadio and write it to this connection."""
        if self.writer is None:
            print(f"[SimRF Bridge] {self.name}: cannot relay, not connected yet")
            return
        to_radio = mesh_pb2.ToRadio()
        to_radio.packet.CopyFrom(packet)
        data = frame(to_radio.SerializeToString())
        try:
            self.writer.write(data)
            await self.writer.drain()
        except Exception as e:
            print(f"[SimRF Bridge] {self.name}: write error: {e}")


async def relay(source: MuxConnection, dest: MuxConnection, seen: RecentlySeen):
    """Connect (with reconnect-with-backoff) to `source`'s mux port, and for
    every complete framed FromRadio packet with `decoded.portnum ==
    SIMULATOR_APP` received from it, relay a copy as a ToRadio packet into
    `dest`'s mux connection - unless `(from, id)` was already relayed in this
    same direction recently (anti-loop, see `seen`)."""
    rx_buf = bytearray()
    while True:
        try:
            print(f"[SimRF Bridge] Connecting to {source.name} mux at {source.host}:{source.port}...")
            reader, writer = await asyncio.open_connection(source.host, source.port)
            source.writer = writer
            print(f"[SimRF Bridge] Connected to {source.name} mux at {source.host}:{source.port}!")
            rx_buf.clear()

            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                rx_buf.extend(chunk)

                while len(rx_buf) >= HEADER_LEN:
                    if rx_buf[0] != START1 or rx_buf[1] != START2:
                        del rx_buf[0]
                        continue

                    packet_len = (rx_buf[2] << 8) | rx_buf[3]
                    total_len = HEADER_LEN + packet_len

                    if len(rx_buf) < total_len:
                        break

                    payload = bytes(rx_buf[HEADER_LEN:total_len])
                    del rx_buf[:total_len]

                    try:
                        from_radio = mesh_pb2.FromRadio.FromString(payload)
                    except Exception:
                        continue

                    if not from_radio.HasField("packet"):
                        continue

                    packet = from_radio.packet
                    if packet.decoded.portnum != portnums_pb2.PortNum.SIMULATOR_APP:
                        continue

                    key = (getattr(packet, "from"), packet.id)
                    if seen.seen(key):
                        # Already relayed this exact packet in this direction
                        # recently - don't bounce it right back and forth.
                        continue

                    print(
                        f"[SimRF Bridge] {source.name} -> {dest.name}: "
                        f"packet id={packet.id} from={getattr(packet, 'from')} "
                        f"to={packet.to} portnum={packet.decoded.portnum}"
                    )

                    seen.add(key)
                    await dest.send_packet(packet)

        except Exception as e:
            print(f"[SimRF Bridge] {source.name}: connection error: {e}")
            source.writer = None
            await asyncio.sleep(2)


async def main():
    rx = MuxConnection("RX", RX_MUX_HOST, RX_MUX_PORT)
    tx = MuxConnection("TX", TX_MUX_HOST, TX_MUX_PORT)

    print("[SimRF Bridge] Starting simulated RF cross-routing bridge...")
    print(f"[SimRF Bridge] RX mux: {RX_MUX_HOST}:{RX_MUX_PORT}  TX mux: {TX_MUX_HOST}:{TX_MUX_PORT}")

    # A single anti-loop cache shared across BOTH directions. Once a given
    # (from, id) packet has been relayed one way, it must never be relayed
    # back the other way - not even after the receiving node performs its
    # own normal mesh-flood rebroadcast of that same packet (which shows up
    # on its mux connection as a fresh outgoing SIMULATOR_APP frame carrying
    # the *same* from/id). Two independent per-direction caches would miss
    # this case and bounce the rebroadcast straight back to the sender,
    # causing duplicate delivery / spurious replay rejections at the
    # receiving end (observed while verifying this bridge end-to-end).
    seen = RecentlySeen()

    await asyncio.gather(
        relay(tx, rx, seen),
        relay(rx, tx, seen),
    )


if __name__ == "__main__":
    asyncio.run(main())
