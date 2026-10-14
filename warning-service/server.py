"""Local-only warning API with asynchronous jobs and persistent result storage."""
import argparse
import csv
import json
import os
import sqlite3
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlsplit
from pathlib import Path

from engine import parse_upload, analyse, InputError
from qwen_advice import generate_advice, public_settings

MAX_BYTES = 10 * 1024 * 1024
LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=2)
DATA_DIR = Path(os.environ.get('RAIN_WARNING_DATA', str(Path(__file__).parent / 'runtime')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / 'jobs.sqlite'


def initialize():
    with sqlite3.connect(str(DB)) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        rows = connection.execute('SELECT id,payload FROM jobs').fetchall()
        for job_id, payload in rows:
            job = json.loads(payload)
            if job['status'] not in ['complete', 'failed']:
                job.update(status='failed', message='服务已重启，请重新提交分析。')
                connection.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job_id))


def save(job):
    with LOCK, sqlite3.connect(str(DB), timeout=20) as connection:
        connection.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (job['id'], json.dumps(job, ensure_ascii=False)))


def load(job_id):
    with LOCK, sqlite3.connect(str(DB), timeout=20) as connection:
        row = connection.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
    return json.loads(row[0]) if row else None


def execute(job, groups):
    try:
        job.update(status='processing', stage='scoring', progress=25, message='正在计算累计降水、站点风险与河段协同性')
        save(job)
        result = analyse(groups, job['meta'])
        job.update(stage='advice', progress=75, message='风险计算完成，正在生成分对象建议', result=result)
        save(job)
        result = generate_advice(result)
        job.update(status='complete', stage='complete', progress=100, message='分析完成', result=result)
        save(job)
    except Exception:
        traceback.print_exc()
        job.update(status='failed', stage='failed', message='分析未完成，请检查CSV后重试。')
        save(job)


class Handler(BaseHTTPRequestHandler):
    server_version = 'RainWarning/1.0'

    def json_response(self, code, body):
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            info = {'status': 'ok', 'version': '1.1'}
            info.update(public_settings())
            return self.json_response(200, info)
        if path.startswith('/jobs/'):
            job_id = path.split('/')[-1]
            if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
                return self.json_response(404, {'error': '未找到任务。'})
            job = load(job_id)
            return self.json_response(200, job) if job else self.json_response(404, {'error': '未找到任务。'})
        return self.json_response(404, {'error': '未找到接口。'})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ['/validate', '/jobs']:
            return self.json_response(404, {'error': '未找到接口。'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BYTES:
                raise InputError('请上传非空CSV，文件大小不超过10 MB。')
            filename = unquote(self.headers.get('X-File-Name', 'upload.csv'))
            if not filename.lower().endswith('.csv'):
                raise InputError('仅支持.csv文件，请下载示例查看格式。')
            raw = self.rfile.read(length)
            groups, meta = parse_upload(raw)
            if path == '/validate':
                return self.json_response(200, {'valid': True, 'meta': meta})
            with LOCK, sqlite3.connect(str(DB)) as connection:
                pending = sum(json.loads(row[0])['status'] not in ['complete', 'failed'] for row in connection.execute('SELECT payload FROM jobs'))
            if pending >= 8:
                return self.json_response(429, {'error': '当前分析任务较多，请稍后重试。'})
            job = {'id': uuid.uuid4().hex, 'filename': filename[:200], 'created_at': datetime.utcnow().isoformat() + 'Z',
                   'status': 'queued', 'stage': 'validated', 'progress': 10, 'message': '校验通过，等待分析', 'meta': meta, 'result': None}
            save(job)
            EXECUTOR.submit(execute, job.copy(), groups)
            return self.json_response(202, job)
        except InputError as error:
            return self.json_response(422, {'error': str(error)})
        except (ValueError, csv.Error):
            return self.json_response(422, {'error': 'CSV格式无法解析，请按示例格式检查。'})
        except Exception:
            traceback.print_exc()
            return self.json_response(500, {'error': '服务暂时无法处理文件，请稍后重试。'})


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8096)
    args = parser.parse_args()
    initialize()
    print('Warning API listening on 127.0.0.1:{}'.format(args.port), flush=True)
    Server(('127.0.0.1', args.port), Handler).serve_forever()
