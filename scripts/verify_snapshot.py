"""Verify the exact server baseline without changing files or contacting a server."""
from pathlib import Path
import hashlib
import json
import tarfile


def verify(repo: Path) -> None:
    manifest = json.loads((repo / 'snapshots/manifest.json').read_text(encoding='utf-8'))
    archive_path = repo / manifest['archive']
    assert archive_path.resolve().is_relative_to(repo.resolve()), 'Unsafe archive path'
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == manifest['archive_sha256'], 'Archive checksum mismatch'
    expected = {entry['path']: entry for entry in manifest['files']}
    seen = set()
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            assert not member.issym() and not member.islnk(), 'Unexpected link'
            assert not member.name.startswith('/') and '..' not in Path(member.name).parts, 'Unsafe member path'
            if not member.isfile():
                continue
            assert member.name in expected and member.name not in seen, 'Unexpected or duplicate file'
            seen.add(member.name)
            with archive.extractfile(member) as source:
                data = source.read()
            entry = expected[member.name]
            assert len(data) == entry['bytes'], 'Size mismatch'
            assert hashlib.sha256(data).hexdigest() == entry['sha256'], 'Member checksum mismatch'
            assert oct(member.mode) == entry['mode'], 'Permissions mismatch'
            if member.name.startswith('data/web/dist/'):
                public_path = repo / 'frontend/dist' / member.name.removeprefix('data/web/dist/')
            elif member.name == 'etc/nginx/conf.d/web.conf':
                public_path = repo / 'deployment/nginx/web.conf'
            else:
                raise AssertionError('Unexpected scope: ' + member.name)
            assert public_path.resolve().is_relative_to(repo.resolve()), 'Unsafe public path'
            assert public_path.read_bytes() == data, 'Public copy differs: ' + member.name
    assert seen == set(expected), 'Missing files'
    print(f'PASS: archive integrity, original modes and all {len(seen)} public files match the server snapshot.')


if __name__ == '__main__':
    verify(Path(__file__).resolve().parents[1])
