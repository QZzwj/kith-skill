import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def write_package(out_dir: Path, slug: str, skill_md: str, memory_md: str,
                  extra: dict[str, str | bytes] | None = None) -> Path:
    """写出技能目录与 zip。

    ``extra`` 是额外的引用文件（相对路径 → 内容），用来放双向蒸馏的
    ``references/self.md``（关于你）/ ``references/other.md``（关于 TA），
    以及参考资料层（逐月原记录、结论依据、原始导出）。

    值是 ``bytes`` 时按字节原样写（原始导出可能是 .db/.mbox 这类非文本文件），
    是 ``str`` 时按 UTF-8 文本写。
    """
    files: dict[str, str | bytes] = {"SKILL.md": skill_md, "references/memory.md": memory_md}
    files.update(extra or {})

    skill_dir = out_dir / slug
    for rel, payload in files.items():
        path = skill_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(payload, encoding="utf-8")
    # 上一次跑双向蒸馏留下的背景资料要清掉：同名目录里留着一份不属于本次运行的
    # references/self.md，很容易被当成这次的产物。
    for rel in ("references/self.md", "references/other.md"):
        if rel not in files:
            (skill_dir / rel).unlink(missing_ok=True)

    zip_path = out_dir / f"{slug}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(skill_dir / rel, rel)
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
