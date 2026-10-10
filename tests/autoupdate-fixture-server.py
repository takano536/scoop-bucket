"""Loopback-only HTTP fixtures for real Scoop checkver/autoupdate tests."""
import hashlib
import http.server
import io
import json
import pathlib
import sys
import zipfile

buffer = io.BytesIO()
with zipfile.ZipFile(buffer, 'w') as archive:
    archive.writestr('app-2.0.0/fixture.txt', 'autoupdate regression fixture\n')
payload = buffer.getvalue()

dev_version = '26.1009.7.410-alpha.dev.1-r1'
dev_commit = 'b' * 40
dev_tag = 'v0.21.6+canary.20261009T070410Z'
dev_name = f'hermes-desktop-light-{dev_version}-windows-x64.zip'
dev_buffer = io.BytesIO()
with zipfile.ZipFile(dev_buffer, 'w') as archive:
    archive.writestr('hermes-light-canary.exe', 'Desktop-release fixture')
dev_payload = dev_buffer.getvalue()
dev_pointer = json.dumps({
    'channel': 'desktop-release',
    'distribution': 'unofficial-light',
    'upstreamChannel': 'canary',
    'version': dev_version,
    'commit': dev_commit,
    'desktopTag': dev_tag,
    'desktopVersion': '26.1009.7.410',
    'sha256': hashlib.sha256(dev_payload).hexdigest(),
    'executable': 'hermes-light-canary.exe',
})


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        bodies = {
            '/latest': b'v2.0.0',
            '/latest/2.0.0': b'v2.0.0',
            '/hash': hashlib.sha256(payload).hexdigest().encode(),
            '/bad-hash': b'0' * 64,
            '/app-2.0.0.zip': payload,
            '/dev-pointer': dev_pointer.encode(),
            '/dev-hash': hashlib.sha256(dev_payload).hexdigest().encode(),
            f'/{dev_name}': dev_payload,
        }
        body = bodies.get(self.path)
        if body is None and self.path.startswith('/dev-') and self.path.endswith('.zip'):
            body = dev_payload
        self.send_response(200 if body is not None else 404)
        self.end_headers()
        self.wfile.write(body if body is not None else b'Not found')


with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
    pathlib.Path(sys.argv[1], 'port.txt').write_text(str(server.server_port))
    server.serve_forever()
