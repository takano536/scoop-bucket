"""Loopback-only HTTP fixtures for real Scoop checkver/autoupdate tests."""
import hashlib
import http.server
import io
import pathlib
import sys
import zipfile

buffer = io.BytesIO()
with zipfile.ZipFile(buffer, 'w') as archive:
    archive.writestr('app-2.0.0/fixture.txt', 'autoupdate regression fixture\n')
payload = buffer.getvalue()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        bodies = {
            '/latest': b'v2.0.0',
            '/latest/2.0.0': b'v2.0.0',
            '/hash': hashlib.sha256(payload).hexdigest().encode(),
            '/bad-hash': b'0' * 64,
            '/app-2.0.0.zip': payload,
        }
        body = bodies.get(self.path)
        self.send_response(200 if body is not None else 404)
        self.end_headers()
        self.wfile.write(body if body is not None else b'Not found')


with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
    pathlib.Path(sys.argv[1], 'port.txt').write_text(str(server.server_port))
    server.serve_forever()
