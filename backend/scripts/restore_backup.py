"""Restore a backup zip from Settings -> Backup.

Stop the server first.

Usage:
    python scripts/restore_backup.py <backup.zip>

Existing data is kept as *.bak-<timestamp>.
"""

from __future__ import annotations

import datetime as dt
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    archive = Path(argv[1])
    if not archive.is_file():
        print(f"File not found: {archive}")
        return 2
    if not settings.resolved_database_url.startswith("sqlite"):
        print("Only SQLite deployments are supported.")
        return 2

    db_path = Path(settings.resolved_database_url.removeprefix("sqlite:///"))
    uploads = settings.uploads_dir
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if "ledger.db" not in names:
            print("Not a Human Ledger backup (ledger.db missing).")
            return 2
        # Only allow known paths (no path traversal).
        for n in names:
            if n not in ("ledger.db", "MANIFEST.txt") and not n.startswith("uploads/"):
                print(f"Unexpected path in backup: {n}")
                return 2
            if ".." in Path(n).parts:
                print(f"Illegal path in backup: {n}")
                return 2

        for suffix in ("", "-wal", "-shm"):
            p = db_path.with_name(db_path.name + suffix)
            if p.exists():
                p.rename(p.with_name(f"{p.name}.bak-{stamp}"))
        if uploads.exists():
            uploads.rename(uploads.with_name(f"uploads.bak-{stamp}"))
        uploads.mkdir(parents=True, exist_ok=True)

        with zf.open("ledger.db") as src, open(db_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        for n in names:
            if n.startswith("uploads/") and not n.endswith("/"):
                target = uploads / Path(n).relative_to("uploads")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(n) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    print(f"Restored: {db_path}")
    print(f"Previous data kept as *.bak-{stamp}.")
    print("Run `python -m alembic upgrade head` before starting (the Docker image does this automatically).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
