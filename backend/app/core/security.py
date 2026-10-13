"""密码哈希与会话令牌。

- 密码：Argon2id（argon2-cffi 默认参数）
- 会话：itsdangerous 签名的 HttpOnly Cookie，无服务端会话表
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

_hasher = PasswordHasher()
_SESSION_SALT = "renlei-zhangben.session.v1"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=_SESSION_SALT)


def create_session_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    """校验并解出 user_id；无效或过期返回 None。"""
    try:
        data = _serializer().loads(token, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None
