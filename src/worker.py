# -*- coding: utf-8 -*-
"""后台单线程：按 PR 防抖，从 GitHub 拉当前状态，发送或更新飞书卡片"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
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


@dataclass
class _Job:
    due: float
    repo: str
    number: int
    # 最近动态 {"text", "at"}；None 表示不改
    activity: dict[str, Any] | None
    # webhook 自带的完整 PR 数据（仅 pull_request 事件），读 PR 无权限时用来生成卡片
    pr: dict[str, Any] | None
    attempt: int = 0


class CardWorker:
    def __init__(self, cfg: Config, gh: GitHubAPI, store: CardStore, user_map: UserMap):
        self.cfg = cfg
        self.gh = gh
        self.store = store
        self.user_map = user_map
        self._cond = threading.Condition()
        self._pending: dict[str, _Job] = {}

    def submit(self, trig: Trigger) -> None:
        activity = {"text": trig.activity, "at": time.time()} if trig.activity else None
        self._schedule(_Job(0, trig.repo, trig.number, activity, trig.pr), DEBOUNCE_SECONDS)

    def _schedule(self, job: _Job, delay: float) -> None:
        key = pr_key(job.repo, job.number)
        with self._cond:
            old = self._pending.get(key)
            if old:
                job.activity = job.activity or old.activity
                job.pr = job.pr or old.pr
            job.due = time.monotonic() + delay
            self._pending[key] = job
            self._cond.notify()

    def _next_due(self) -> _Job:
        with self._cond:
            while True:
                if not self._pending:
                    self._cond.wait()
                    continue
                key, job = min(self._pending.items(), key=lambda kv: kv[1].due)
                wait = job.due - time.monotonic()
                if wait <= 0:
                    del self._pending[key]
                    return job
                self._cond.wait(wait)

    def run(self) -> None:
        while True:
            job = self._next_due()
            try:
                ok = self._refresh(job)
            except Exception:
                log.exception("[%s#%s] refresh crashed", job.repo, job.number)
                ok = True
            if not ok:
                if job.attempt < MAX_RETRIES:
                    log.warning("[%s#%s] refresh failed, retry in %ss", job.repo, job.number, RETRY_DELAY_SECONDS)
                    job.attempt += 1
                    self._schedule(job, RETRY_DELAY_SECONDS)
                else:
                    log.error("[%s#%s] refresh failed, giving up", job.repo, job.number)

    def _refresh(self, job: _Job) -> bool:
        """返回 False 表示可重试的失败（网络、5xx、限流）。无权限（401/403/404）不重试，在卡片上提示。"""
        repo, number = job.repo, job.number
        ctx = f"[{repo}#{number}]"
        key = pr_key(repo, number)
        rec = self.store.get(key)
        # 读取失败的部分：{"pr" | "reviews" | "comments": HTTP 状态码}
        errors: dict[str, int] = {}

        def fetch(name: str, fn):
            try:
                return fn(repo, number)
            except GitHubAPIError as e:
                if not e.permanent:
                    raise
                log.warning("%s GitHub no access: %s", ctx, e)
                errors[name] = e.status
                return None

        try:
            pr = fetch("pr", self.gh.get_pull) or job.pr
            if pr is None:
                log.warning("%s no PR data, card unchanged", ctx)
                return True
            state = pr_state(pr)
            # 未发过卡片且不需要发（Draft / 已关闭）时不必再拉 reviews 和评论
            if not rec and state != "open":
                log.info("%s skip state=%s (no card)", ctx, state)
                return True
            reviews = fetch("reviews", self.gh.list_reviews)
            comments = fetch("comments", self.gh.list_issue_comments)
            # 合并/关闭后的卡片只有一行，不需要文件明细
            files = None if state in ("merged", "closed") else fetch("files", self.gh.list_files)
        except GitHubAPIError as e:
            log.warning("%s GitHub error: %s", ctx, e)
            return False

        token = get_tenant_access_token(self.cfg.app_id, self.cfg.app_secret)
        if not token:
            return False

        activity = job.activity or (rec or {}).get("activity")
        card = build_status_card(pr, reviews, comments, activity, repo, self.user_map.as_dict(), errors, files)
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
