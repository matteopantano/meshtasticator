import asyncio
import tornado.ioloop
import tornado.web
import tornado.websocket

MESHTASTIC_HOST = "meshtasticd"
MESHTASTIC_PORT = 4403
START1 = 0x94
START2 = 0xc3
HEADER_LEN = 4

ws_clients = set()
http_fromradio_queue = asyncio.Queue()
tcp_writer_global = None

class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, PATCH")
        self.set_header("Access-Control-Allow-Headers", "*")

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

class RootHTTPHandler(BaseHandler):
    def get(self, *args, **kwargs):
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok", "meshtastic": True})

    def post(self, *args, **kwargs):
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok", "meshtastic": True})

    def put(self, *args, **kwargs):
        self.set_header("Content-Type", "application/json")
        self.write({"status": "ok", "meshtastic": True})

class FromRadioHandler(BaseHandler):
    async def get(self, *args, **kwargs):
        self.set_header("Content-Type", "application/x-protobuf")
        try:
            data = await asyncio.wait_for(http_fromradio_queue.get(), timeout=1.5)
            self.write(data)
        except asyncio.TimeoutError:
            self.write(b"")

    async def post(self, *args, **kwargs):
        await self.get(*args, **kwargs)

class ToRadioHandler(BaseHandler):
    async def post(self, *args, **kwargs):
        await self._handle_toradio()

    async def put(self, *args, **kwargs):
        await self._handle_toradio()

    async def _handle_toradio(self):
        body = self.request.body
        if body and tcp_writer_global:
            msg_len = len(body)
            header = bytes([START1, START2, (msg_len >> 8) & 0xFF, msg_len & 0xFF])
            tcp_writer_global.write(header + body)
            await tcp_writer_global.drain()
        self.set_header("Content-Type", "application/x-protobuf")
        self.write(b"")

class WSHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

    def open(self, *args, **kwargs):
        print("WebSocket connected from browser")
        ws_clients.add(self)

    def on_message(self, message):
        if isinstance(message, str):
            message = message.encode("latin1")
        if tcp_writer_global and isinstance(message, (bytes, bytearray)):
            msg_len = len(message)
            header = bytes([START1, START2, (msg_len >> 8) & 0xFF, msg_len & 0xFF])
            tcp_writer_global.write(header + message)
            asyncio.create_task(tcp_writer_global.drain())

    def on_close(self):
        print("WebSocket closed")
        ws_clients.discard(self)

async def meshtastic_tcp_loop():
    global tcp_writer_global
    rx_buf = bytearray()
    while True:
        try:
            print("Connecting background proxy loop to meshtasticd TCP 4403...")
            reader, writer = await asyncio.open_connection(MESHTASTIC_HOST, MESHTASTIC_PORT)
            tcp_writer_global = writer
            print("Background proxy loop connected to meshtasticd TCP 4403!")
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

                    if http_fromradio_queue.qsize() < 100:
                        http_fromradio_queue.put_nowait(payload)

                    for ws in list(ws_clients):
                        try:
                            ws.write_message(payload, binary=True)
                        except Exception:
                            ws_clients.discard(ws)

        except Exception as e:
            print("TCP loop connection error:", e)
            tcp_writer_global = None
            await asyncio.sleep(2)

def make_app():
    return tornado.web.Application([
        (r"/api/v1/ws.*", WSHandler),
        (r"/ws.*", WSHandler),
        (r"/api/v1/fromradio.*", FromRadioHandler),
        (r"/api/v1/toradio.*", ToRadioHandler),
        (r"/.*", RootHTTPHandler),
    ])

if __name__ == "__main__":
    app = make_app()
    app.listen(4403)
    loop = asyncio.get_event_loop()
    loop.create_task(meshtastic_tcp_loop())
    print("Proxy listening on port 4403 with persistent TCP queue manager...")
    loop.run_forever()
