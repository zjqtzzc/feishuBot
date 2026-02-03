# -*- coding: utf-8 -*-
"""飞书凭据管理：tenant_access_token 的获取与文件缓存，过期自动刷新"""

import json
import os
import time

import requests

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
    r = requests.post(AUTH_URL, json={"app_id": app_id, "app_secret": app_secret}, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise Exception(f"获取凭证失败：{data.get('msg', '未知错误')}")
    token = data["tenant_access_token"]
    save_token(token_file, token, int(time.time()) + data.get("expire", 7200) - token_buffer)
    return token


PR_MESSAGE_MAP_FILENAME = ".pr_message_map"
MAX_MAPPINGS = 50


class PrMessageMapping:
    def __init__(self, map_file: str, max_entries: int = MAX_MAPPINGS):
        self.map_file = map_file
        self.max_entries = max_entries
        self._data: list[tuple[str, str]] = []
        self._load()

    def _load(self):
        if not os.path.exists(self.map_file):
            self._data = []
            return
        try:
            with open(self.map_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._data = [tuple(x) for x in raw.get("mapping", [])]
        except Exception:
            self._data = []

    def _save(self):
        with open(self.map_file, "w", encoding="utf-8") as f:
            json.dump({"mapping": [[k, v] for k, v in self._data]}, f)

    def _pr_key(self, repo_name: str, pr_number: str | int) -> str:
        return f"{repo_name}#{pr_number}"

    def get(self, repo_name: str, pr_number: str | int) -> str | None:
        key = self._pr_key(repo_name, pr_number)
        for k, v in reversed(self._data):
            if k == key:
                return v
        return None

    def set(self, repo_name: str, pr_number: str | int, message_id: str):
        key = self._pr_key(repo_name, pr_number)
        self._data = [(k, v) for k, v in self._data if k != key]
        self._data.append((key, message_id))
        if len(self._data) > self.max_entries:
            self._data = self._data[-self.max_entries:]
        self._save()
