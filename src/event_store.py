# -*- coding: utf-8 -*-
"""PR 时间线持久化：.pr_event_store JSON，按 repo#pr 维度存储事件与飞书 message_id"""

import fcntl
import json
import os
from typing import Any, Callable


EVENT_STORE_FILENAME = ".pr_event_store"
MAX_PR_RECORDS = 20


def pr_key(repo_full_name: str, pr_number: str | int) -> str:
    return f"{repo_full_name}#{pr_number}"


def trim_pr_record_count(data: dict[str, Any]) -> None:
    """超过 MAX_PR_RECORDS 时按 last_touched 最旧优先删除。"""
    if len(data) <= MAX_PR_RECORDS:
        return
    keys_by_age = sorted(
        data.keys(),
        key=lambda k: (data[k].get("last_touched") or "", k),
    )
    while len(data) > MAX_PR_RECORDS and keys_by_age:
        oldest = keys_by_age.pop(0)
        data.pop(oldest, None)


class EventStore:
    def __init__(self, path: str):
        self.path = path

    def _mutate(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                raw = f.read()
                data: dict[str, Any] = json.loads(raw) if raw.strip() else {}
                result = fn(data)
                trim_pr_record_count(data)
                f.seek(0)
                f.truncate(0)
                f.write(json.dumps(data, ensure_ascii=False, indent=2))
                f.flush()
                os.fsync(f.fileno())
                return result
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def get(self, repo_full_name: str, pr_number: str | int) -> dict[str, Any] | None:
        if not os.path.exists(self.path):
            return None
        with open(self.path, "r", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                raw = f.read()
                data: dict[str, Any] = json.loads(raw) if raw.strip() else {}
                return data.get(pr_key(repo_full_name, pr_number))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def get_readonly(self, repo_full_name: str, pr_number: str | int) -> dict[str, Any] | None:
        """不加锁只读，用于读多写少场景；写路径请用 mutate。"""
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        return data.get(pr_key(repo_full_name, pr_number))

    def mutate(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        return self._mutate(fn)

    def remove_record(self, repo_full_name: str, pr_number: str | int) -> None:
        k = pr_key(repo_full_name, pr_number)

        def fn(data: dict[str, Any]):
            data.pop(k, None)

        self._mutate(fn)

    def put_record(self, key: str, record: dict[str, Any]):
        def fn(data: dict[str, Any]):
            data[key] = record

        self._mutate(fn)

    def update_record(self, repo_full_name: str, pr_number: str | int, updater: Callable[[dict[str, Any]], None]):
        k = pr_key(repo_full_name, pr_number)

        def fn(data: dict[str, Any]):
            rec = data.get(k)
            if rec is None:
                return
            updater(rec)
            data[k] = rec

        self._mutate(fn)
