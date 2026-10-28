# -*- coding: utf-8 -*-
"""GitHub Webhook：验签，并把事件归类为「刷新哪个 PR 的卡片 + 最近动态文案」。

卡片内容一律从 GitHub 当前状态生成，这里不解析业务细节。
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from src.config import Config
from src.feishu_card import is_ai_comment

HANDLED_EVENTS = ("pull_request", "pull_request_review", "issue_comment")


@dataclass
class Trigger:
    repo: str
    number: int
    # 最近动态（lark_md）；None 表示只刷新卡片、不改最近动态
    activity: str | None
    # pull_request 事件自带的完整 PR 数据；读 PR 无权限时用它生成卡片
    pr: dict[str, Any] | None = None


@dataclass
class Result:
    code: int
    # 成功时为 queued / ignored，失败时为错误信息
    status: str
    # 以下仅用于日志：被忽略的原因等、owner/repo#n
    detail: str = ""
    tag: str = "?"
    trigger: Trigger | None = None


def verify_signature(payload: bytes, sig: str, secret: str) -> bool:
    if not secret:
        return True
    expect = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expect)


def _team_or_login(obj: dict[str, Any] | None) -> str:
    obj = obj or {}
    if obj.get("login"):
        return obj["login"]
    slug = obj.get("slug") or obj.get("name")
    return f"team/{slug}" if slug else ""


def _pull_request_activity(data: dict[str, Any], actor: str) -> tuple[bool, str | None]:
    action = data.get("action", "")
    pr = data.get("pull_request") or {}
    if action == "synchronize":
        return True, f"**{actor}** pushed `{(data.get('after') or '')[:7]}`"
    if action == "closed":
        return True, f"**{actor}** {'merged' if pr.get('merged') else 'closed'}"
    if action == "review_requested":
        return True, f"**{actor}** requested review from **{_team_or_login(data.get('requested_reviewer') or data.get('requested_team'))}**"
    simple = {
        "opened": "opened",
        "reopened": "reopened",
        "ready_for_review": "marked ready for review",
        "converted_to_draft": "converted to draft",
    }
    if action in simple:
        return True, f"**{actor}** {simple[action]}"
    if action in ("edited", "review_request_removed"):
        return True, None
    return False, None


def _review_activity(data: dict[str, Any]) -> tuple[bool, str | None]:
    action = data.get("action", "")
    if action == "dismissed":
        return True, None
    if action != "submitted":
        return False, None
    review = data.get("review") or {}
    user = (review.get("user") or {}).get("login", "")
    verb = {"approved": "approved", "changes_requested": "requested changes"}.get(
        (review.get("state") or "").lower(), "reviewed"
    )
    return True, f"**{user}** {verb}"


def _comment_activity(data: dict[str, Any]) -> tuple[bool, str | None]:
    action = data.get("action", "")
    if action == "deleted":
        return True, None
    if action != "created":
        return False, None
    comment = data.get("comment") or {}
    user = (comment.get("user") or {}).get("login", "")
    if is_ai_comment(comment):
        return True, "AI review 已更新"
    return True, f"**{user}** commented"


def handle(
    payload: bytes,
    sig: str,
    event_type: str,
    data: dict[str, Any] | None,
    cfg: Config,
) -> Result:
    if event_type not in HANDLED_EVENTS:
        return Result(200, "ignored", event_type or "unknown")
    if not data:
        return Result(400, "Empty payload")
    if not verify_signature(payload, sig, cfg.github_webhook_secret):
        return Result(401, "Invalid signature")

    repo = (data.get("repository") or {}).get("full_name", "")
    if event_type == "issue_comment":
        issue = data.get("issue") or {}
        number = int(issue.get("number") or 0)
        tag = f"{repo}#{number}"
        if "pull_request" not in issue:
            return Result(200, "ignored", "not_a_pr", tag)
        handled, activity = _comment_activity(data)
    else:
        number = int((data.get("pull_request") or {}).get("number") or 0)
        tag = f"{repo}#{number}"
        if event_type == "pull_request":
            actor = (data.get("sender") or {}).get("login", "")
            handled, activity = _pull_request_activity(data, actor)
        else:
            handled, activity = _review_activity(data)

    if not handled:
        return Result(200, "ignored", data.get("action") or "unknown", tag)
    if not repo or not number:
        return Result(400, "Missing repo/pr", tag=tag)
    pr = data.get("pull_request") if event_type == "pull_request" else None
    return Result(200, "queued", tag=tag, trigger=Trigger(repo, number, activity, pr))
