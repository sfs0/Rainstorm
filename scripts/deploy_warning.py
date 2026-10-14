"""Deploy the first warning module without modifying the Java backend.

SSH password is read from stdin and is never stored in the repository.
Requires paramiko on the deploying workstation, not on the server.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import io
import json
import sys
import tarfile

import paramiko

ROOT = Path(__file__).resolve().parents[1]
build = json.loads((ROOT / 'build/build-manifest.json').read_text(encoding='utf-8'))
version = build['version']
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
route = (ROOT / 'deployment/nginx/web.conf').read_bytes()
needle = b'root /data/web/dist;'
if route.count(needle) != 1:
    raise SystemExit('Baseline route does not match expected root.')
new_route = route.replace(needle, needle + b'''\n
    location ^~ /rain-warning-api/ {
        client_max_body_size 10m;
        proxy_pass http://127.0.0.1:8096/;
        proxy_read_timeout 120s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
''', 1)
new_route = new_route.replace(b'try_files $uri $uri/ /index.html;',
    b'try_files $uri $uri/ /index.html;\n        add_header Cache-Control "no-cache" always;')
(ROOT / 'build/web-warning.conf').write_bytes(new_route)

buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
    for path in (ROOT / 'build/web/dist').rglob('*'):
        if path.is_file(): archive.add(path, arcname='web/' + path.relative_to(ROOT / 'build/web/dist').as_posix())
    for name in ['server.py', 'engine.py', 'station_catalog.json', 'example.csv']:
        archive.add(ROOT / 'warning-service' / name, arcname='service/' + name)
    archive.add(ROOT / 'deployment/rainstorm-warning.service', arcname='rainstorm-warning.service')
    archive.add(ROOT / 'build/web-warning.conf', arcname='web-warning.conf')
raw = buffer.getvalue()
release_file = ROOT / 'build' / ('rain-warning-' + version + '.tar.gz')
release_file.write_bytes(raw)
sha = hashlib.sha256(raw).hexdigest()
remote_archive = '/tmp/rain-warning-' + version + '.tar.gz'
staging = '/tmp/rain-warning-' + version + '-' + stamp
backup = '/data/web/releases/before-warning-' + stamp

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('8.130.160.137', username='root', password=sys.stdin.readline().rstrip('\r\n'),
               timeout=20, look_for_keys=False, allow_agent=False)
sftp = client.open_sftp()
sftp.put(str(release_file), remote_archive)
sftp.close()
command = r'''set -e
test -d /data/web/dist
test ! -L /data/web/dist
test -f /etc/nginx/conf.d/web.conf
test ! -L /etc/nginx/conf.d/web.conf
actual=$(sha256sum __ARCHIVE__ | cut -d ' ' -f1)
test "$actual" = '__SHA__'
mkdir -p __STAGING__
tar -xzf __ARCHIVE__ -C __STAGING__
install -d -m 755 /opt/rainstorm-warning
install -d -o nginx -g nginx -m 750 /var/lib/rainstorm-warning
cp __STAGING__/service/* /opt/rainstorm-warning/
chmod 644 /opt/rainstorm-warning/*
/usr/bin/python3 -m py_compile /opt/rainstorm-warning/engine.py /opt/rainstorm-warning/server.py
cp __STAGING__/rainstorm-warning.service /etc/systemd/system/rainstorm-warning.service
systemctl daemon-reload
systemctl enable rainstorm-warning
systemctl restart rainstorm-warning
for attempt in 1 2 3 4 5; do
    if curl --max-time 3 -fsS http://127.0.0.1:8096/health; then break; fi
    sleep 1
done
curl --max-time 3 -fsS http://127.0.0.1:8096/health
mkdir -p __BACKUP__
cp -p /etc/nginx/conf.d/web.conf __BACKUP__/web.conf
cp -a __STAGING__/web __BACKUP__/new-dist
mv /data/web/dist __BACKUP__/dist
mv __BACKUP__/new-dist /data/web/dist
cp __STAGING__/web-warning.conf /etc/nginx/conf.d/web.conf
if ! nginx -t; then
    cp -p __BACKUP__/web.conf /etc/nginx/conf.d/web.conf
    mv /data/web/dist __BACKUP__/failed-dist
    mv __BACKUP__/dist /data/web/dist
    exit 1
fi
if ! systemctl reload nginx; then
    cp -p __BACKUP__/web.conf /etc/nginx/conf.d/web.conf
    mv /data/web/dist __BACKUP__/failed-dist
    mv __BACKUP__/dist /data/web/dist
    systemctl reload nginx
    exit 1
fi
systemctl enable nginx
printf '\nDEPLOYMENT COMPLETE\n'
systemctl is-active rainstorm-warning nginx
curl --max-time 5 -fsS http://127.0.0.1/rain-warning-api/health
printf '\n'
'''
for key, value in {'__ARCHIVE__': remote_archive, '__SHA__': sha, '__STAGING__': staging, '__BACKUP__': backup}.items():
    command = command.replace(key, value)
_, stdout, stderr = client.exec_command(command, timeout=60)
output = stdout.read().decode('utf-8', 'replace')
error = stderr.read().decode('utf-8', 'replace')
status = stdout.channel.recv_exit_status()
print(output)
print(error)
client.close()
if status:
    raise SystemExit('Deployment stopped; status {}'.format(status))
record = {'version': version, 'deployed_at_utc': datetime.now(timezone.utc).isoformat(),
          'server': '8.130.160.137', 'release_sha256': sha, 'previous_web_backup': backup,
          'frontend_build': build, 'backend_service': 'rainstorm-warning', 'backend_port': '127.0.0.1:8096',
          'preview_url': 'http://8.130.160.137/#/home/analyse?tool=rainstorm'}
(ROOT / 'build/deployment-record.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print('Previous webpage preserved at:', backup)
