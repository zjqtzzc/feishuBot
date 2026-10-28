# -*- coding: utf-8 -*-
"""飞书 tenant_access_token：进程内缓存与刷新"""

import logging
import threading
import time

import requests
from requests.exceptions import RequestException

log = logging.getLogger(__name__)

AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"

_lock = threading.Lock()
_token: str | None = None
_expire_at = 0.0


def get_tenant_access_token(
    app_id: str,
    app_secret: str,
    token_buffer: int = 100,
    timeout: int = 10,
) -> str | None:
    global _token, _expire_at
    with _lock:
        if _token and _expire_at > time.time() + token_buffer:
            return _token
        log.debug("Feishu token refresh (network)")
        try:
            r = requests.post(AUTH_URL, json={"app_id": app_id, "app_secret": app_secret}, timeout=timeout)
            data = r.json()
        except (RequestException, ValueError) as e:
            log.error("Feishu token refresh error: %s", e)
            return None
        if data.get("code") != 0:
            log.error("Feishu token refresh failed: %s", data.get("msg", data))
            return None
        _token = data["tenant_access_token"]
        _expire_at = time.time() + data.get("expire", 7200)
        log.debug("Feishu token refresh ok")
        return _token
