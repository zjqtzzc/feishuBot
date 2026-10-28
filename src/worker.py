# -*- coding: utf-8 -*-
"""后台单线程：按 PR 防抖，从 GitHub 拉当前状态，发送或更新飞书卡片"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from src.card_store import CardStore, pr_key
from src.config import Config
from src.feishu_api import RATE_LIMIT_CODES, patch_interactive_card, send_interactive_card
from src.feishu_card import build_status_card, pr_state
from src.feishu_credential import get_tenant_access_token
from src.github_api import GitHubAPI, GitHubAPIError
from src.handlers import Trigger
from src.user_map import UserMap

log = logging.getLogger(__name__)

# 同一 PR 在这段时间内的连续事件只刷新一次
DEBOUNCE_SECONDS = 2.5
# GitHub / 飞书出错时的重试
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 30


class CardWorker:
    def __init__(self, cfg: Config, gh: GitHubAPI, store: CardStore, user_map: UserMap):
        self.cfg = cfg
        self.gh = gh
        self.store = store
        self.user_map = user_map
        self._cond = threading.Condition()
        # key → (到期时间, repo, number, 最近动态, 已重试次数)
        self._pending: dict[str, tuple[float, str, int, dict[str, Any] | None, int]] = {}

    def submit(self, trig: Trigger) -> None:
        activity = {"text": trig.activity, "at": time.time()} if trig.activity else None
        self._schedule(trig.repo, trig.number, activity, DEBOUNCE_SECONDS, 0)

    def _schedule(self, repo: str, number: int, activity: dict[str, Any] | None, delay: float, attempt: int) -> None:
        key = pr_key(repo, number)
        with self._cond:
            old = self._pending.get(key)
            if activity is None and old:
                activity = old[3]
            self._pending[key] = (time.monotonic() + delay, repo, number, activity, attempt)
            self._cond.notify()

    def _next_due(self) -> tuple[str, int, dict[str, Any] | None, int]:
        with self._cond:
            while True:
                if not self._pending:
                    self._cond.wait()
                    continue
                key, item = min(self._pending.items(), key=lambda kv: kv[1][0])
                wait = item[0] - time.monotonic()
                if wait <= 0:
                    del self._pending[key]
                    return item[1:]
                self._cond.wait(wait)

    def run(self) -> None:
        while True:
            repo, number, activity, attempt = self._next_due()
            try:
                ok = self._refresh(repo, number, activity)
            except Exception:
                log.exception("[%s#%s] refresh crashed", repo, number)
                ok = True
            if not ok:
                if attempt < MAX_RETRIES:
                    log.warning("[%s#%s] refresh failed, retry in %ss", repo, number, RETRY_DELAY_SECONDS)
                    self._schedule(repo, number, activity, RETRY_DELAY_SECONDS, attempt + 1)
                else:
                    log.error("[%s#%s] refresh failed, giving up", repo, number)

    def _refresh(self, repo: str, number: int, activity: dict[str, Any] | None) -> bool:
        """返回 False 表示可重试的失败。"""
        ctx = f"[{repo}#{number}]"
        key = pr_key(repo, number)
        rec = self.store.get(key)
        try:
            pr = self.gh.get_pull(repo, number)
            state = pr_state(pr)
            # 未发过卡片且不需要发（Draft / 已关闭）时不必再拉 reviews 和评论
            if not rec and state != "open":
                log.info("%s skip state=%s (no card)", ctx, state)
                return True
            reviews = self.gh.list_reviews(repo, number)
            comments = self.gh.list_issue_comments(repo, number)
        except GitHubAPIError as e:
            log.warning("%s GitHub error: %s", ctx, e)
            return False

        token = get_tenant_access_token(self.cfg.app_id, self.cfg.app_secret)
        if not token:
            return False

        activity = activity or (rec or {}).get("activity")
        card = build_status_card(pr, reviews, comments, activity, repo, self.user_map.as_dict())
        closed = state in ("merged", "closed")
        closed_at = ((rec or {}).get("closed_at") or time.time()) if closed else None

        if rec:
            code = patch_interactive_card(token, rec["message_id"], card, ctx=ctx)
            if code == 0:
                self.store.put(key, {**rec, "closed_at": closed_at, "activity": activity})
                return True
            if code is None or code in RATE_LIMIT_CODES:
                return False
            # 卡片已失效（被撤回/删除/超期等）：已关闭的不再重发，进行中的发新卡片
            log.warning("%s card unusable code=%s, %s", ctx, code, "drop" if closed else "resend")
            self.store.delete(key)
            if closed:
                return True

        mid = send_interactive_card(token, self.cfg.chat_id, card, ctx=ctx)
        if not mid:
            return False
        self.store.put(key, {"message_id": mid, "sent_at": time.time(), "closed_at": closed_at, "activity": activity})
        return True
