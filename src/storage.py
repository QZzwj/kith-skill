"""Local state is kept beside packages, never inside exported skills."""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


def lock(root: Path):
    key = str(root.resolve())
    with _GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def local_dir(root: Path) -> Path:
    return root.parent / '.kith' / root.name


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load(path: Path, default=None):
    if not path.exists():
        return default
    # Corrupt state must be surfaced, not silently overwritten.
    return json.loads(path.read_text(encoding='utf-8'))


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(dumps(value), encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not relative or path == root.resolve() or not path.is_relative_to(root.resolve()):
        raise ValueError('文件路径必须位于技能目录内')
    return path
