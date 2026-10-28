# -*- coding: utf-8 -*-
"""GitHub → 飞书用户映射表，持久化到 .user_map.json

格式：{github 用户名: {"open_id": ..., "name": 飞书名字}}；兼容旧格式 {github 用户名: open_id}。
"""

from __future__ import annotations

import json
import logging
import os
import threading

log = logging.getLogger(__name__)

USER_MAP_FILENAME = ".user_map.json"


class UserMap:
    def __init__(self, filepath: str):
        self._filepath = filepath
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._filepath):
            return
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load user map: %s", e)
            return
        for gh, v in raw.items():
            self._data[gh] = {"open_id": v, "name": ""} if isinstance(v, str) else v

    def _save(self) -> None:
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            log.error("Failed to save user map: %s", e)

    # ── CRUD ────────────────────────────────────────────

    def bind(self, github_name: str, open_id: str, name: str = "") -> None:
        with self._lock:
            self._data[github_name] = {"open_id": open_id, "name": name}
            self._save()

    def unbind(self, github_name: str) -> bool:
        with self._lock:
            if github_name not in self._data:
                return False
            del self._data[github_name]
            self._save()
            return True

    def set_names(self, names: dict[str, str]) -> None:
        """按 open_id 补全飞书名字。"""
        with self._lock:
            changed = False
            for v in self._data.values():
                name = names.get(v["open_id"])
                if name and name != v.get("name"):
                    v["name"] = name
                    changed = True
            if changed:
                self._save()

    def list_all(self) -> dict[str, dict[str, str]]:
        with self._lock:
            return {gh: dict(v) for gh, v in self._data.items()}

    def as_dict(self) -> dict[str, str]:
        """github 用户名 → open_id，供卡片 @mention。"""
        with self._lock:
            return {gh: v["open_id"] for gh, v in self._data.items()}
