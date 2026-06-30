"""鉴权：密码哈希 + JWT.

- 密码直接用 bcrypt 库哈希（不经 passlib，避免 passlib 与新版 bcrypt 的兼容问题）。
- 访问令牌用 JWT（PyJWT），载荷含 user_id 与 username。

注：bcrypt 只取密码前 72 字节，超长部分本就被忽略；这里显式截断到 72 字节，
既符合 bcrypt 行为，又避免新版 bcrypt 对超长输入抛 ValueError。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

_MAX_BCRYPT_BYTES = 72


def _to_bytes(raw: str) -> bytes:
    return raw.encode("utf-8")[:_MAX_BCRYPT_BYTES]


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(_to_bytes(raw), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(raw), hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def create_access_token(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解码并校验 JWT，返回载荷；失败抛 jwt 异常。"""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
