"""从「设置 → 备份」下载的 zip 恢复数据库与上传文件。

**必须先停掉服务**再运行：SQLite 文件被替换时若仍有连接打开，WAL 里的旧内容
会在下次 checkpoint 时覆盖刚恢复的数据。

用法：
    backend/.venv/Scripts/python.exe scripts/restore_backup.py <备份 zip>

现有的 ledger.db 与 uploads/ 会先改名为 *.bak-<时间戳> 留在原目录，
确认恢复无误后可手动删除。
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
        print(f"找不到文件：{archive}")
        return 2
    if not settings.resolved_database_url.startswith("sqlite"):
        print("只支持 SQLite 部署。")
        return 2

    db_path = Path(settings.resolved_database_url.removeprefix("sqlite:///"))
    uploads = settings.uploads_dir
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if "ledger.db" not in names:
            print("这不是人类账本的备份包（缺少 ledger.db）。")
            return 2
        # zip 内路径只允许 ledger.db / uploads/... / MANIFEST.txt，防止路径穿越
        for n in names:
            if n not in ("ledger.db", "MANIFEST.txt") and not n.startswith("uploads/"):
                print(f"备份包含意外的路径：{n}")
                return 2
            if ".." in Path(n).parts:
                print(f"备份包含非法路径：{n}")
                return 2

        # 先把现有数据挪开（含 WAL / SHM 伴随文件），失败也不会丢
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

    print(f"已恢复：{db_path}")
    print(f"旧数据保留为 *.bak-{stamp}，确认无误后可删除。")
    print("启动前请运行 python -m alembic upgrade head，以防备份来自旧版本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
