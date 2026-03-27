# -*- coding: utf-8 -*-
"""飞书 tenant_access_token 缓存与刷新"""

import json
import logging
import os
import time

import requests
from requests.exceptions import RequestException

log = logging.getLogger(__name__)

AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_TOKEN_FILENAME = ".feishu_token"


def load_token(token_file: str) -> tuple[str | None, int]:
    if not os.path.exists(token_file):
        return None, 0
    try:
        with open(token_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("tenant_access_token"), int(data.get("expire_at", 0))
    except Exception:
        return None, 0


def save_token(token_file: str, token: str, expire_at: int):
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump({"tenant_access_token": token, "expire_at": expire_at}, f)


def get_tenant_access_token(
    app_id: str,
    app_secret: str,
    token_file: str,
    token_buffer: int = 100,
    timeout: int = 10,
) -> str | None:
    token, expire_at = load_token(token_file)
    if token and expire_at > int(time.time()) + token_buffer:
        return token
    log.debug("Feishu token refresh (network)")
    try:
        r = requests.post(AUTH_URL, json={"app_id": app_id, "app_secret": app_secret}, timeout=timeout)
        r.raise_for_status()
    except RequestException as e:
        log.error("Feishu token refresh network error: %s", e)
        return None
    data = r.json()
    if data.get("code") != 0:
        log.error("Feishu token refresh failed: %s", data.get("msg", data))
        return None
    token = data["tenant_access_token"]
    save_token(token_file, token, int(time.time()) + data.get("expire", 7200) - token_buffer)
    log.debug("Feishu token refresh ok")
    return token
