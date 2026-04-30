# -*- coding: utf-8 -*-
"""GitHub → 飞书用户映射表，持久化到 .user_map.json"""

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
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._filepath):
            return
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load user map: %s", e)
            self._data = {}

    def _save(self) -> None:
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            log.error("Failed to save user map: %s", e)

    # ── CRUD ────────────────────────────────────────────

    def bind(self, github_name: str, open_id: str) -> None:
        with self._lock:
            self._data[github_name] = open_id
            self._save()

    def unbind(self, github_name: str) -> bool:
        with self._lock:
            if github_name not in self._data:
                return False
            del self._data[github_name]
            self._save()
            return True

    def find_by_open_id(self, open_id: str) -> str | None:
        with self._lock:
            for gh, oid in self._data.items():
                if oid == open_id:
                    return gh
            return None

    def find_by_github(self, github_name: str) -> str | None:
        with self._lock:
            return self._data.get(github_name)

    def list_all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._data)

    def as_dict(self) -> dict[str, str]:
        """向卡片渲染暴露只读快照。"""
        return self.list_all()
