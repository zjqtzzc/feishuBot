# -*- coding: utf-8 -*-
"""飞书卡片：按 PR 维度加锁，send 或 patch 交互卡片"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from src.config import Config
from src.event_store import EventStore, pr_key
from src.feishu_api import patch_interactive_card, send_interactive_card
from src.feishu_card import build_timeline_card
from src.feishu_credential import get_tenant_access_token

log = logging.getLogger(__name__)

# 同一 PR 并发 webhook（如 opened + ready_for_review、重试等）会并发 _sync_card，若都见 message_id 为空会各发一条飞书消息
_pr_sync_locks: dict[str, threading.Lock] = {}
_pr_sync_locks_guard = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sync_lock_for_pr(repo_name: str, pr_number: int) -> threading.Lock:
    k = pr_key(repo_name, pr_number)
    with _pr_sync_locks_guard:
        if k not in _pr_sync_locks:
            _pr_sync_locks[k] = threading.Lock()
        return _pr_sync_locks[k]


def _sync_card(
    cfg: Config,
    token_file: str,
    store: EventStore,
    repo_name: str,
    pr_number: int,
) -> bool:
    with _sync_lock_for_pr(repo_name, pr_number):
        rec = store.get(repo_name, pr_number)
        if not rec:
            return False
        t0 = time.monotonic()
        ctx = f"[{repo_name}#{pr_number}]"
        token = get_tenant_access_token(cfg.app_id, cfg.app_secret, token_file)
        log.info("%s token ok %.3fs", ctx, time.monotonic() - t0)
        if not token:
            return False
        card = build_timeline_card(rec)
        mid = rec.get("message_id")
        if mid:
            return patch_interactive_card(token, mid, card, ctx=ctx)
        new_id = send_interactive_card(token, cfg.chat_id, card, ctx=ctx)
        if not new_id:
            return False

        k = pr_key(repo_name, pr_number)

        def fn(data: dict[str, Any]):
            if k in data:
                data[k]["message_id"] = new_id
                data[k]["last_touched"] = _now_iso()

        store.mutate(fn)
        return True


def sync_card_if_published(
    cfg: Config,
    token_file: str,
    store: EventStore,
    repo_name: str,
    pr_number: int,
    *,
    publish_first: bool,
) -> bool:
    """未发过飞书（无 message_id）时仅当 publish_first（非 Draft 的 opened，或 ready_for_review）才真正 send/patch。"""
    rec = store.get(repo_name, pr_number)
    if not rec:
        return False
    if rec.get("message_id") or publish_first:
        return _sync_card(cfg, token_file, store, repo_name, pr_number)
    return True
