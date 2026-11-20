import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKUPS = Path(os.environ.get("OPS_DATA_DIR", HERE)) / "backups"
KEEP = 200


def testing():
    return "unittest" in sys.modules


def _inside(path, roots):
    p = Path(path).resolve()
    return any(p == r or r in p.parents for r in roots)


def allow_write(path):
    """Under a test run only scratch paths may be written; a real file means the test isolation broke."""
    if not testing():
        return
    roots = [Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve(), Path("/private/tmp")]
    if os.environ.get("OPS_DATA_DIR"):
        roots.append(Path(os.environ["OPS_DATA_DIR"]).resolve())
    if not _inside(path, roots):
        raise RuntimeError(f"test run tried to write a real file: {path}")


def allow_keychain():
    if testing():
        raise RuntimeError("test run tried to change the macOS Keychain")


def backup(path, kind):
    """Copy a file (or folder) into backups/<kind>/ before it is changed or removed; identical copies are skipped."""
    path = Path(path)
    if testing() or not path.exists():
        return None
    folder = BACKUPS / kind
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    dest = folder / f"{stamp}-{path.name}"
    if path.is_dir():
        shutil.copytree(path, dest)
    else:
        last = sorted(folder.glob(f"*-{path.name}"))
        if last and last[-1].is_file() and last[-1].read_bytes() == path.read_bytes():
            return last[-1]
        shutil.copy2(path, dest)
        os.chmod(dest, 0o600)
    for old in sorted(folder.iterdir())[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
    return dest


def listing():
    if not BACKUPS.exists():
        return []
    return sorted((p for k in BACKUPS.iterdir() if k.is_dir() for p in k.iterdir()), key=lambda p: p.name)
