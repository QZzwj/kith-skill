"""Immutable local snapshots, provenance and human-readable changes."""
import hashlib
import re
import uuid
import zipfile
from pathlib import Path

from . import storage


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest(files: dict, metadata: dict | None = None) -> dict:
    return {'schema_version': 1, 'version': uuid.uuid4().hex[:16],
            'created_at': storage.now(), 'metadata': metadata or {},
            'files': {name: digest(payload if isinstance(payload, bytes) else payload.encode('utf-8'))
                      for name, payload in sorted(files.items()) if name != 'manifest.json'}}


def current_files(root: Path) -> dict[str, bytes]:
    current = storage.load(storage.local_dir(root) / 'current.json', {})
    names = set(current.get('files', {})) | {'SKILL.md', 'references/memory.md'}
    if not current:
        # The old ZIP tells us which files the generator owned. User additions
        # outside it must survive regeneration and rollback.
        archive_path = root.parent / (root.name + '.zip')
        if archive_path.is_file():
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    names.update(n for n in archive.namelist() if not n.endswith('/')
                                 and '.kith' not in Path(n).parts and n != 'manifest.json')
            except (OSError, zipfile.BadZipFile):
                pass
    return {name: storage.safe_path(root, name).read_bytes() for name in names
            if storage.safe_path(root, name).is_file()}


def fingerprint(root: Path) -> str:
    return digest(storage.dumps({name: digest(data) for name, data in sorted(current_files(root).items())}).encode())


def snapshot(root: Path, reason: str, metadata: dict | None = None) -> dict | None:
    if not (root / 'SKILL.md').is_file():
        return None
    files = current_files(root)
    listing = {name: digest(data) for name, data in sorted(files.items())}
    history = list_versions(root)
    if history and history[0]['files'] == listing:
        return history[0]
    current = storage.load(storage.local_dir(root) / 'current.json', {})
    version = manifest(files, metadata or current.get('metadata'))
    version['reason'] = reason
    version['package_version'] = current.get('version', '')
    destination = storage.local_dir(root) / 'versions' / version['version']
    for name, data in files.items():
        path = storage.safe_path(destination / 'files', name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    storage.write(destination / 'manifest.json', version)
    storage.write(storage.local_dir(root) / 'current.json', version)
    return version


def record(root: Path, names, metadata: dict | None = None, reason: str = '生成') -> dict:
    """Record only managed package files; local review state is never exported."""
    files = {name: storage.safe_path(root, name).read_bytes() for name in names}
    version = manifest(files, metadata)
    version['reason'] = reason
    destination = storage.local_dir(root) / 'versions' / version['version']
    for name, data in files.items():
        path = storage.safe_path(destination / 'files', name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    storage.write(destination / 'manifest.json', version)
    storage.write(storage.local_dir(root) / 'current.json', version)
    return version


def current(root: Path) -> dict:
    return storage.load(storage.local_dir(root) / 'current.json', {})


def state(root: Path) -> dict:
    info = current(root)
    listing = {name: digest(data) for name, data in current_files(root).items()}
    return {'version': info.get('version', ''), 'fingerprint': fingerprint(root),
            'modified': listing != info.get('files', {}), 'metadata': info.get('metadata', {})}


def rollback(root: Path, version: str) -> dict:
    """Validate the snapshot before any mutation; preserve feedback and user files."""
    from .package import write_package
    with storage.lock(root):
        files = read_version(root, version)
        info = storage.load(storage.local_dir(root) / 'versions' / version / 'manifest.json')
        write_package(root.parent, root.name, files.pop('SKILL.md'), files.pop('references/memory.md'),
                      extra=files, metadata=info.get('metadata', {}), reason='回滚至 ' + version)
        return current(root)


def list_versions(root: Path) -> list[dict]:
    folder = storage.local_dir(root) / 'versions'
    history = [storage.load(p) for p in folder.glob('*/manifest.json')]
    # UUIDs are random; file modification time breaks same-second ties.
    history.sort(key=lambda v: (folder / v['version'] / 'manifest.json').stat().st_mtime_ns, reverse=True)
    return history


def read_version(root: Path, version: str) -> dict[str, bytes]:
    if not re.fullmatch(r'[a-f0-9]{16}', version or ''):
        raise ValueError('版本编号不合法')
    destination = storage.local_dir(root) / 'versions' / version
    info = storage.load(destination / 'manifest.json')
    if not info:
        raise ValueError('版本不存在')
    files = {name: storage.safe_path(destination / 'files', name).read_bytes() for name in info['files']}
    if any(digest(data) != info['files'][name] for name, data in files.items()):
        raise ValueError('版本快照校验失败，未执行回滚')
    return files


def diff(root: Path, version: str) -> dict:
    before, after = read_version(root, version), current_files(root)
    changed = sorted(name for name in before.keys() & after.keys() if before[name] != after[name])
    details = []
    for name in changed:
        if not name.endswith(('.md', '.json', '.txt')):
            continue
        import difflib
        old, new = before[name].decode('utf-8', 'replace'), after[name].decode('utf-8', 'replace')
        lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile='历史/' + name,
                                       tofile='当前/' + name, lineterm=''))
        details.append({'file': name, 'diff': '\n'.join(lines[:600]), 'truncated': len(lines) > 600})
    return {'added': sorted(after.keys() - before.keys()), 'removed': sorted(before.keys() - after.keys()),
            'changed': changed, 'details': details}
