"""CONNECT-only HTTPS proxy: explicit provider hosts, no arbitrary outbound URLs."""
import select
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED_HOSTS = frozenset({
    "accounts.google.com", "oauth2.googleapis.com", "sheets.googleapis.com",
    "www.googleapis.com", "auth.openai.com", "api.openai.com", "chatgpt.com",
    "www.nasdaqtrader.com",
})


class Proxy(BaseHTTPRequestHandler):
    def do_CONNECT(self):
        host, _, port = self.path.rpartition(":")
        if host not in ALLOWED_HOSTS or port != "443":
            self.send_error(403, "Destination is not allowed")
            return
        try:
            upstream = socket.create_connection((host, 443), timeout=20)
        except OSError:
            self.send_error(502, "Provider unavailable")
            return
        with upstream:
            self.send_response(200, "Connection established")
            self.end_headers()
            sockets = [self.connection, upstream]
            try:
                while True:
                    readable, _, _ = select.select(sockets, [], [], 180)
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        target = upstream if source is self.connection else self.connection
                        target.sendall(data)
            except OSError:
                return

    def log_message(self, *_args):
        # Never log request headers, provider URL paths or tokens.
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 3128), Proxy).serve_forever()
