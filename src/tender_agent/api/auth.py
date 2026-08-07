import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    nick_name: str = ""


_USER_CACHE: dict[str, tuple[float, AuthUser]] = {}


def _auth_enabled() -> bool:
    return os.getenv("EXTERNAL_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _extract_user(payload: object) -> AuthUser:
    if not isinstance(payload, dict):
        raise ValueError("getInfo returned a non-object response")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    user_data = data.get("user") if isinstance(data.get("user"), dict) else data
    user_id = str(user_data.get("userId") or "").strip()
    if not user_id:
        raise ValueError("getInfo response does not contain userId")
    return AuthUser(
        user_id=user_id,
        nick_name=str(user_data.get("nickName") or user_data.get("userName") or "").strip(),
    )


def _fetch_user_info(token: str) -> AuthUser:
    cookie_name = os.getenv("EXTERNAL_AUTH_COOKIE_NAME", "External-Auth-Token").strip()
    url = os.getenv("EXTERNAL_AUTH_GETINFO_URL", "").strip()
    if not url:
        raise ValueError("EXTERNAL_AUTH_GETINFO_URL is required when external authentication is enabled")
    timeout = max(1.0, float(os.getenv("EXTERNAL_AUTH_TIMEOUT_SECONDS", "8")))
    request = UrlRequest(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": token,
            "ClientType": "2",
            "Cookie": f"{cookie_name}={token}",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return _extract_user(payload)


async def get_current_user(request: Request) -> AuthUser:
    if not _auth_enabled():
        return AuthUser(
            user_id=os.getenv("EXTERNAL_AUTH_DEV_USER_ID", "local-dev").strip() or "local-dev",
            nick_name=os.getenv("EXTERNAL_AUTH_DEV_NICK_NAME", "Local Developer").strip(),
        )

    cookie_name = os.getenv("EXTERNAL_AUTH_COOKIE_NAME", "External-Auth-Token").strip()
    token = str(request.cookies.get(cookie_name) or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")

    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    cached = _USER_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    try:
        user = await asyncio.to_thread(_fetch_user_info, token)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录") from exc
        raise HTTPException(status_code=503, detail="外部用户信息接口暂时不可用") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="外部用户信息接口暂时不可用") from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="无法识别当前登录用户") from exc

    ttl = max(0.0, float(os.getenv("EXTERNAL_AUTH_CACHE_TTL_SECONDS", "120")))
    _USER_CACHE[cache_key] = (now + ttl, user)
    if len(_USER_CACHE) > 1000:
        expired = [key for key, (expires_at, _) in _USER_CACHE.items() if expires_at <= now]
        for key in expired:
            _USER_CACHE.pop(key, None)
    return user
