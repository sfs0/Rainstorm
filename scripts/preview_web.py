"""Local UI test harness. Legacy file-list API is an empty fixture.

The synthetic session is strictly limited to this local origin and never
forwarded to the real Java backend. CSV jobs go to the local warning service.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import mimetypes
import json

ROOT = Path(__file__).resolve().parents[1] / 'build/web/dist'


class Handler(BaseHTTPRequestHandler):
    def handle_warning(self):
        path = self.path[len('/rain-warning-api'):]
        body = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if self.command == 'POST' else None
        headers = {key: self.headers[key] for key in ['Content-Type', 'X-File-Name'] if self.headers.get(key)}
        request = Request('http://127.0.0.1:18096' + path, data=body, headers=headers, method=self.command)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        data = response.read()
        self.send_response(response.code)
        self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
        self.send_header('Content-Length', str(len(data)))
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/rain-warning-api/'):
            return self.handle_warning()
        if path.startswith('/api/'):
            data = json.dumps({'code': 0, 'data': {'records': [], 'current': 1, 'size': 10, 'total': 0}}).encode()
            mime = 'application/json'
        else:
            target = (ROOT / path.lstrip('/')).resolve()
            if not target.is_relative_to(ROOT.resolve()):
                self.send_error(403);return
            if not target.is_file():target = ROOT / 'index.html'
            data = target.read_bytes()
            mime = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            if target.name == 'index.html':
                data = data.replace(b'<head>', b'<head><script>sessionStorage.setItem("token","LOCAL_PREVIEW_FIXTURE_ONLY");</script>')
        self.send_response(200);self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store');self.send_header('Content-Length', str(len(data)))
        self.end_headers();self.wfile.write(data)

    def do_POST(self):
        if self.path.startswith('/rain-warning-api/'):
            return self.handle_warning()
        self.send_error(404)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    print('Local fixture preview: http://127.0.0.1:18080/#/home/analyse?tool=rainstorm', flush=True)
    Server(('127.0.0.1', 18080), Handler).serve_forever()
