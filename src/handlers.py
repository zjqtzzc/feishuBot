# -*- coding: utf-8 -*-
"""GitHub Webhook 处理：pull_request / pull_request_review / issue_comment"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

from src.config import Config
from src.event_store import EventStore, pr_key
from src.feishu_card import (
    extract_ai_review_for_card,
    is_claude_ai_comment,
    strip_blockquote_lines,
    truncate_issue_comment_body,
)
from src.feishu_sync import sync_card_if_published
from src.github_api import GitHubAPI, GitHubAPITimeout
from src.timeline_event_type import TimelineEventType


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_from_pr(pr: dict[str, Any]) -> str:
    return pr.get("updated_at") or pr.get("created_at") or _now_iso()


def pr_state_from_payload(pr: dict[str, Any]) -> str:
    if pr.get("merged"):
        return "merged"
    if pr.get("state") == "closed":
        return "closed"
    return "open"


def _label_requested_reviewer(obj: dict[str, Any] | None) -> str:
    if not obj:
        return ""
    lg = obj.get("login")
    if lg:
        return lg
    slug = obj.get("slug") or obj.get("name")
    if slug:
        return f"team/{slug}"
    return ""


def verify_signature(payload: bytes, sig: str, secret: str) -> bool:
    if not secret:
        return True
    expect = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expect)


def new_record(
    repo: str,
    pr_number: int,
    pr_url: str,
    pr_title: str,
    pr_state: str,
) -> dict[str, Any]:
    return {
        "message_id": None,
        "pr_state": pr_state,
        "pr_title": pr_title,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "repo": repo,
        "events": [],
        "last_touched": _now_iso(),
    }


def _ensure_record(
    store: EventStore,
    repo_name: str,
    pr: dict[str, Any],
) -> None:
    k = pr_key(repo_name, pr["number"])
    st = pr_state_from_payload(pr)

    def fn(data: dict[str, Any]):
        if k not in data:
            data[k] = new_record(
                repo_name,
                int(pr["number"]),
                pr.get("html_url", ""),
                pr.get("title", ""),
                st,
            )

    store.mutate(fn)


def _append_event(
    store: EventStore,
    repo_name: str,
    pr_number: int,
    event: dict[str, Any],
    record_updates: dict[str, Any] | None = None,
) -> None:
    k = pr_key(repo_name, pr_number)
    ru = dict(record_updates or {})
    ru["last_touched"] = _now_iso()

    def fn(data: dict[str, Any]):
        rec = data.get(k)
        if rec is None:
            return
        rec.setdefault("events", []).append(event)
        rec.update(ru)
        data[k] = rec

    store.mutate(fn)


def _has_comment_id_seen(store: EventStore, repo_name: str, pr_number: int, comment_id: int) -> bool:
    """同一 issue_comment id 只处理一次（含 AI 与普通评论）。"""
    if not comment_id:
        return False
    rec = store.get(repo_name, pr_number)
    if not rec:
        return False
    for ev in rec.get("events") or []:
        if ev.get("comment_id") == comment_id:
            return True
    return False



def handle_pull_request(
    data: dict[str, Any],
    cfg: Config,
    token_file: str,
    store: EventStore,
    gh: GitHubAPI,
) -> tuple[dict, int]:
    action = data.get("action", "")
    if action not in (
        "opened",
        "synchronize",
        "reopened",
        "edited",
        "closed",
        "review_requested",
        "ready_for_review",
    ):
        return {"status": "ignored", "action": action or "unknown"}, 200

    pr = data.get("pull_request") or {}
    repo = data.get("repository") or {}
    repo_name = repo.get("full_name", "")
    pr_number = int(pr.get("number") or 0)
    if not repo_name or not pr_number:
        return {"error": "Missing repo/pr"}, 400

    sender = data.get("sender") or {}
    sender_login = sender.get("login", "")

    _ensure_record(store, repo_name, pr)

    if action == "edited":
        title = pr.get("title", "")

        def fn2(data2: dict[str, Any]):
            k = pr_key(repo_name, pr_number)
            if k in data2:
                data2[k]["pr_title"] = title
                data2[k]["last_touched"] = _now_iso()

        store.mutate(fn2)
        ok = sync_card_if_published(cfg, token_file, store, repo_name, pr_number, publish_first=False)
        return ({"status": "success", "detail": "title_edited"}, 200) if ok else ({"error": "Feishu update failed"}, 500)

    st = pr_state_from_payload(pr)
    tm = _iso_from_pr(pr)
    detail = ""

    if action == "opened":
        try:
            file_stat = gh.format_git_file_stats(repo_name, pr_number)
        except GitHubAPITimeout:
            file_stat = "⚠️ GitHub 连接超时，无法获取文件列表"
        except Exception:
            file_stat = "⚠️ GitHub 文件列表获取失败"
        ev: dict[str, Any] = {
            "type": TimelineEventType.PR_OPEN.value,
            "time": tm,
            "author": sender_login,
            "title": pr.get("title", ""),
            "pr_number": pr_number,
            "file_stat": file_stat,
        }
        _append_event(
            store,
            repo_name,
            pr_number,
            ev,
            {
                "pr_state": st,
                "pr_title": pr.get("title", ""),
                "pr_url": pr.get("html_url", ""),
            },
        )
        detail = "pr_open"
    elif action == "synchronize":
        before = data.get("before") or ""
        after = data.get("after") or pr.get("head", {}).get("sha", "")
        branch = (pr.get("head") or {}).get("ref", "")
        try:
            total, short_sha, msgs = gh.get_commits_between(repo_name, before, after)
            if total <= 0 and after:
                total = 1
                if not short_sha:
                    short_sha = after[:7]
                if not msgs:
                    t = gh.get_commit_title_line(repo_name, after)
                    msgs = [t] if t else []
            if total == 1 and after and (not msgs or not str(msgs[0]).strip()):
                t = gh.get_commit_title_line(repo_name, after)
                if t:
                    msgs = [t]
        except GitHubAPITimeout:
            total, short_sha, msgs = 1, after[:7] if after else "", []
        except Exception:
            total, short_sha, msgs = 1, after[:7] if after else "", []
        ev = {
            "type": TimelineEventType.PR_PUSH.value,
            "time": tm,
            "author": sender_login,
            "branch": branch,
            "head_sha": short_sha or (after[:7] if after else ""),
            "commit_count": total,
            "commit_messages": msgs,
        }
        _append_event(store, repo_name, pr_number, ev, {"pr_state": st, "pr_title": pr.get("title", "")})
        detail = "pr_push"
    elif action == "review_requested":
        label = _label_requested_reviewer(data.get("requested_reviewer"))
        if label:
            ev = {
                "type": TimelineEventType.REVIEW_REQUESTED.value,
                "time": tm,
                "requester": sender_login,
                "reviewer": label,
            }
            _append_event(store, repo_name, pr_number, ev, {"pr_state": st, "pr_title": pr.get("title", "")})
            detail = "review_requested"
    elif action == "ready_for_review":
        ev = {"type": TimelineEventType.PR_READY.value, "time": tm, "author": sender_login}
        _append_event(store, repo_name, pr_number, ev, {"pr_state": st, "pr_title": pr.get("title", "")})
        detail = "pr_ready"
    elif action == "reopened":
        ev = {"type": TimelineEventType.PR_REOPEN.value, "time": tm, "author": sender_login}
        _append_event(store, repo_name, pr_number, ev, {"pr_state": "open", "pr_title": pr.get("title", "")})
        detail = "pr_reopen"
    elif action == "closed":
        if pr.get("merged"):
            ev = {"type": TimelineEventType.PR_MERGE.value, "time": tm, "merger": sender_login}
            _append_event(store, repo_name, pr_number, ev, {"pr_state": "merged", "pr_title": pr.get("title", "")})
            detail = "pr_merge"
        else:
            ev = {"type": TimelineEventType.PR_CLOSE.value, "time": tm, "author": sender_login}
            _append_event(store, repo_name, pr_number, ev, {"pr_state": "closed", "pr_title": pr.get("title", "")})
            detail = "pr_close"

    # Draft：仅写 store，ready_for_review 时首次发群；非 Draft：opened 即首次发群。request review 不再作为首次触发。
    if action == "opened":
        publish_first = not pr.get("draft", False)
    elif action == "ready_for_review":
        publish_first = True
    else:
        publish_first = False
    ok = sync_card_if_published(cfg, token_file, store, repo_name, pr_number, publish_first=publish_first)
    if ok and action == "closed" and pr.get("merged"):
        store.remove_record(repo_name, pr_number)
    if ok:
        return {"status": "success", "detail": detail or "sync"}, 200
    return ({"error": "Feishu send/update failed"}, 500)


def handle_pull_request_review(
    data: dict[str, Any],
    cfg: Config,
    token_file: str,
    store: EventStore,
) -> tuple[dict, int]:
    if data.get("action") != "submitted":
        return {"status": "ignored", "action": data.get("action", "")}, 200

    pr = data.get("pull_request") or {}
    review = data.get("review") or {}
    repo = data.get("repository") or {}
    repo_name = repo.get("full_name", "")
    pr_number = int(pr.get("number") or 0)
    if not repo_name or not pr_number:
        return {"error": "Missing repo/pr"}, 400

    _ensure_record(store, repo_name, pr)
    st = (review.get("state") or "").lower()
    user = (review.get("user") or {}).get("login", "")
    tm = review.get("submitted_at") or _iso_from_pr(pr)
    body = (review.get("body") or "").strip()
    ev = {
        "type": TimelineEventType.HUMAN_REVIEW.value,
        "time": tm,
        "reviewer": user,
        "state": st,
        "body": body,
    }
    _append_event(store, repo_name, pr_number, ev, {"pr_state": pr_state_from_payload(pr), "pr_title": pr.get("title", "")})
    ok = sync_card_if_published(cfg, token_file, store, repo_name, pr_number, publish_first=False)
    return ({"status": "success", "detail": "human_review"}, 200) if ok else ({"error": "Feishu send/update failed"}, 500)


def handle_issue_comment(
    data: dict[str, Any],
    cfg: Config,
    token_file: str,
    store: EventStore,
) -> tuple[dict, int]:
    if data.get("action") != "created":
        return {"status": "ignored", "action": data.get("action", "")}, 200

    issue = data.get("issue") or {}
    if not issue.get("pull_request"):
        return {"status": "ignored", "reason": "not_a_pr"}, 200

    comment = data.get("comment") or {}
    body = comment.get("body") or ""
    repo = data.get("repository") or {}
    repo_name = repo.get("full_name", "")
    pr_number = int(issue.get("number") or 0)
    comment_id = int(comment.get("id") or 0)
    author = (comment.get("user") or {}).get("login", "")
    tm = comment.get("updated_at") or comment.get("created_at") or _now_iso()

    if not repo_name or not pr_number:
        return {"error": "Missing repo/pr"}, 400

    if comment_id and _has_comment_id_seen(store, repo_name, pr_number, comment_id):
        return {"status": "ignored", "reason": "duplicate_comment"}, 200

    k = pr_key(repo_name, pr_number)
    pr_url = issue.get("html_url", "")
    title = issue.get("title", "")
    st = "closed" if issue.get("state") == "closed" else "open"

    def ensure_from_issue(d: dict[str, Any]):
        if k not in d:
            d[k] = new_record(repo_name, pr_number, pr_url, title, st)

    store.mutate(ensure_from_issue)

    if is_claude_ai_comment(body, comment):
        review_text = extract_ai_review_for_card(body)
        ev = {
            "type": TimelineEventType.AI_REVIEW.value,
            "time": tm,
            "author": author,
            "comment_id": comment_id,
            "final_opinion": review_text,
        }
        _append_event(store, repo_name, pr_number, ev, {"pr_title": issue.get("title", "")})
        ok = sync_card_if_published(cfg, token_file, store, repo_name, pr_number, publish_first=False)
        return ({"status": "success", "detail": "ai_review"}, 200) if ok else ({"error": "Feishu send/update failed"}, 500)

    plain = strip_blockquote_lines(body)
    if not plain:
        return {"status": "ignored", "reason": "empty_comment"}, 200

    ev = {
        "type": TimelineEventType.PR_COMMENT.value,
        "time": tm,
        "author": author,
        "comment_id": comment_id,
        "body": truncate_issue_comment_body(plain),
    }
    _append_event(store, repo_name, pr_number, ev, {"pr_title": issue.get("title", "")})
    ok = sync_card_if_published(cfg, token_file, store, repo_name, pr_number, publish_first=False)
    return ({"status": "success", "detail": "pr_comment"}, 200) if ok else ({"error": "Feishu send/update failed"}, 500)


def handle(
    payload: bytes,
    sig: str,
    event_type: str,
    data: dict[str, Any] | None,
    cfg: Config,
    token_file: str,
    store_path: str,
    gh: GitHubAPI,
) -> tuple[dict, int]:
    if event_type not in ("pull_request", "pull_request_review", "issue_comment"):
        return {"status": "ignored", "event": event_type or "unknown"}, 200
    if not data:
        return {"error": "Empty payload"}, 400
    if not verify_signature(payload, sig, cfg.github_webhook_secret):
        return {"error": "Invalid signature"}, 401

    store = EventStore(store_path)

    if event_type == "pull_request":
        return handle_pull_request(data, cfg, token_file, store, gh)
    if event_type == "pull_request_review":
        return handle_pull_request_review(data, cfg, token_file, store)
    if event_type == "issue_comment":
        return handle_issue_comment(data, cfg, token_file, store)

    return {"status": "ignored", "event": event_type or "unknown"}, 200
