"""忘记密码时重设：给指定用户换一个随机的新密码并打印出来。

用法：
    backend/.venv/Scripts/python.exe scripts/reset_password.py            列出所有用户名
    backend/.venv/Scripts/python.exe scripts/reset_password.py <用户名>   重设该用户的密码

新密码只打印这一次，不写进任何文件。只改密码，账目不受影响；服务开着也可以运行。
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

# 去掉 0/o、1/l/i 这类容易看错、念错的字符
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _new_password() -> str:
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3))


def main(argv: list[str]) -> int:
    with SessionLocal() as db:
        if len(argv) == 1:
            names = db.execute(select(User.username).order_by(User.id)).scalars().all()
            if not names:
                print("还没有用户：打开网页会进入初始化页面。")
                return 0
            print("用户：")
            for n in names:
                print(f"  {n}")
            return 0
        if len(argv) != 2:
            print(__doc__)
            return 2
        user = db.execute(select(User).where(User.username == argv[1])).scalar_one_or_none()
        if user is None:
            print(f"没有用户「{argv[1]}」。不带参数运行可以列出所有用户名。")
            return 1
        password = _new_password()
        user.password_hash = hash_password(password)
        db.commit()
    print(f"已重设「{argv[1]}」的密码。新密码：{password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
