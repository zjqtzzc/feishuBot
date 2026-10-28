# -*- coding: utf-8 -*-
"""已发飞书卡片记录：repo#pr → message_id 等，持久化为 JSON。

只由 worker 单线程读写，不加锁。
"""

import calendar
import json
import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)

# 沿用旧文件名：升级前已发出的卡片 message_id 继续可用
CARD_STORE_FILENAME = ".pr_event_store"

# 合并/关闭后保留多久（期间的评论等仍可更新卡片）
CLOSED_TTL = 24 * 3600
# 飞书只能更新 14 天内发出的消息；超期删记录，下次事件会发新卡片
CARD_TTL = 14 * 24 * 3600


def pr_key(repo_full_name: str, pr_number: str | int) -> str:
    return f"{repo_full_name}#{pr_number}"


def _parse_ts(v: Any) -> float:
    """兼容旧记录里的 ISO 时间字符串。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v:
        try:
            return float(calendar.timegm(time.strptime(v, "%Y-%m-%dT%H:%M:%SZ")))
        except ValueError:
            pass
    return time.time()


class CardStore:
    def __init__(self, path: str):
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load card store: %s", e)
                raw = {}
            for k, rec in raw.items():
                if rec.get("message_id"):
                    self._data[k] = {
                        "message_id": rec["message_id"],
                        "sent_at": _parse_ts(rec.get("sent_at") or rec.get("last_touched")),
                        "closed_at": rec.get("closed_at"),
                        "activity": rec.get("activity"),
                    }
        self._prune()

    def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    def put(self, key: str, rec: dict[str, Any]) -> None:
        self._data[key] = rec
        self._save()

    def delete(self, key: str) -> None:
        if self._data.pop(key, None) is not None:
            self._save()

    def _prune(self) -> None:
        now = time.time()
        for k in list(self._data):
            rec = self._data[k]
            closed_at = rec.get("closed_at")
            if now - rec["sent_at"] > CARD_TTL or (closed_at and now - closed_at > CLOSED_TTL):
                del self._data[k]

    def _save(self) -> None:
        self._prune()
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError as e:
            log.error("Failed to save card store: %s", e)
