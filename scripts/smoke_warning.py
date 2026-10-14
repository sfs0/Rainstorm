"""Check a deployed build and submit only the repository's public sample CSV."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    args = parser.parse_args()
    base = args.url.rstrip('/')

    def request(path, data=None):
        req = Request(base + path, data=data, headers={'X-File-Name': 'example.csv'})
        with urlopen(req, timeout=20) as response:
            return response.status, response.read()

    manifest = json.loads((ROOT / 'build/build-manifest.json').read_text())
    for name, expected in manifest['frontend_files'].items():
        _, raw = request('/' + name + '?build=' + manifest['version'])
        assert hashlib.sha256(raw).hexdigest() == expected, name
    print('Frontend files match:', len(manifest['frontend_files']), manifest['version'])
    _, raw = request('/rain-warning-api/health')
    assert json.loads(raw)['status'] == 'ok'
    sample = (ROOT / 'warning-service/example.csv').read_bytes()
    _, raw = request('/rain-warning-api/validate', sample)
    assert json.loads(raw)['meta']['basin'] == '长江'
    status, raw = request('/rain-warning-api/jobs', sample)
    assert status == 202
    job_id = json.loads(raw)['id']
    deadline = time.monotonic() + 30
    while True:
        _, raw = request('/rain-warning-api/jobs/' + job_id)
        job = json.loads(raw)
        if job['status'] in ['complete', 'failed']:
            break
        assert time.monotonic() < deadline, 'Job did not finish'
        time.sleep(0.5)
    assert job['status'] == 'complete', job['message']
    assert job['progress'] == 100
    result = job['result']
    assert [x['max_risk_index'] for x in result['reaches']] == [22.5, 22.17, 9.33]
    assert result['generation']['method'] == 'rule'
    assert all(result['advice'][x] for x in ['overview', 'public', 'traffic', 'water', 'emergency', 'uncertainty'])
    try:
        request('/rain-warning-api/validate', b'wrong,columns\n1,2\n')
    except HTTPError as error:
        assert error.code == 422
    else:
        raise AssertionError('Invalid CSV was accepted')
    print('Sample validation, analysis, advice and invalid CSV checks passed.')


if __name__ == '__main__':
    main()
