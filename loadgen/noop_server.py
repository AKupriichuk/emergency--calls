"""Trivial no-op HTTP server used only to calibrate the load generator's own
ceiling, independent of the service under test."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class NoopHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        pass


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 9000), NoopHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
