import sys
import urllib.error
import urllib.request
import zipfile
import re
import tempfile
from pathlib import Path

from . import storage, versions


def write_package(out_dir: Path, slug: str, skill_md: str | bytes, memory_md: str | bytes,
                  extra: dict[str, str | bytes] | None = None, metadata: dict | None = None,
                  reason: str = '生成') -> Path:
    """写出技能目录与 zip。

    ``extra`` 是额外的引用文件（相对路径 → 内容），用来放双向蒸馏的
    ``references/self.md``（关于你）/ ``references/other.md``（关于 TA），
    以及参考资料层（逐月原记录、结论依据、原始导出）。

    值是 ``bytes`` 时按字节原样写（原始导出可能是 .db/.mbox 这类非文本文件），
    是 ``str`` 时按 UTF-8 文本写。
    """
    files: dict[str, str | bytes] = {"SKILL.md": skill_md, "references/memory.md": memory_md}
    files.update(extra or {})
    if not re.fullmatch(r'[\w.\-]+', slug) or slug.lower() in ('.', '..', '.kith'):
        raise ValueError('技能名只允许字母、数字、下划线、点和短横线')
    skill_dir = out_dir / slug
    zip_path = out_dir / f"{slug}.zip"
    # Validate every destination before writing even one file.
    for rel in files:
        storage.safe_path(skill_dir, rel)
        if '.kith' in [part.lower() for part in re.split(r'[/\\]', rel)] or rel.lower() == 'manifest.json':
            raise ValueError('本地工作台状态不能进入技能包')
    out_dir.mkdir(parents=True, exist_ok=True)
    with storage.lock(skill_dir):
        versions.snapshot(skill_dir, '修改前保存')
        previous_files = set(versions.current(skill_dir).get('files', {}))
        if not previous_files and zip_path.exists():
            try:
                with zipfile.ZipFile(zip_path) as previous:
                    previous_files = {info.filename for info in previous.infolist() if not info.is_dir()}
            except (OSError, zipfile.BadZipFile):
                pass
        old = versions.current_files(skill_dir)
        for rel in files:
            destination = storage.safe_path(skill_dir, rel)
            if destination.is_file():
                old[rel] = destination.read_bytes()
        old_zip = zip_path.read_bytes() if zip_path.exists() else None
        old_manifest = versions.current(skill_dir)
        stale = previous_files - files.keys()
        with tempfile.TemporaryDirectory(prefix='.kith-stage-', dir=out_dir) as folder:
            staged = Path(folder)
            for rel, payload in files.items():
                path = storage.safe_path(staged, rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload if isinstance(payload, bytes) else payload.encode('utf-8'))
            pending_zip = staged / '_package.zip'
            with zipfile.ZipFile(pending_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
                for rel in files:
                    archive.write(staged / rel, rel)
            try:
                for rel in files:
                    destination = storage.safe_path(skill_dir, rel)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes((staged / rel).read_bytes())
                for rel in stale:
                    path = storage.safe_path(skill_dir, rel)
                    if path.is_file():
                        path.unlink()
                        parent = path.parent
                        while parent != skill_dir and parent.is_dir() and not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent
                pending_zip.replace(zip_path)
                # Keep metadata small and never persist runtime credentials.
                allowed = {key: value for key, value in (metadata or old_manifest.get('metadata', {})).items()
                           if key in ('audience', 'engine', 'relation', 'redacted')}
                versions.record(skill_dir, files, allowed, reason)
            except Exception:
                for rel in files.keys() | previous_files:
                    path = storage.safe_path(skill_dir, rel)
                    if rel in old:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(old[rel])
                    elif path.is_file():
                        path.unlink()
                if old_zip is not None:
                    zip_path.write_bytes(old_zip)
                else:
                    zip_path.unlink(missing_ok=True)
                storage.write(storage.local_dir(skill_dir) / 'current.json', old_manifest)
                raise
    return zip_path


def upload_to_device(device: str, slug: str, zip_path: Path) -> bool:
    url = f"http://{device}/api/skills/upload"
    data = zip_path.read_bytes()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/zip", "X-Skill-Name": slug},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            print(f"  · 上传结果：{resp.status} {resp.read().decode('utf-8', 'ignore')[:200]}")
        return True
    except urllib.error.HTTPError as e:
        print(f"  ! 上传失败：{e.code} {e.read().decode('utf-8', 'ignore')[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"  ! 上传失败：{e}", file=sys.stderr)
    return False


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
