# -*- coding: utf-8 -*-
"""飞书时间线卡片：从 PR 记录构建 interactive 卡片"""

from __future__ import annotations

import re
from typing import Any, Callable

from src.timeline_event_type import TimelineEventType

TYPE_TEMPLATE = {"open": "red", "merged": "green", "closed": "grey"}

# 与 handlers.pr_state_from_payload 一致，共 3 种
PR_STATE_HEADER_EN = {"open": "Open", "merged": "Merged", "closed": "Closed"}

MAX_SINGLE_EVENT_CHARS = 2000
MAX_TIMELINE_CHARS = 22000
MAX_ISSUE_COMMENT_BODY = 100


def strip_blockquote_lines(text: str) -> str:
    """去掉 Markdown 引用行（> …），回复里只保留用户自写内容。"""
    out: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            continue
        out.append(line)
    return "\n".join(out).strip()


def truncate_issue_comment_body(s: str, max_len: int = MAX_ISSUE_COMMENT_BODY) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"


def truncate_text(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 8] + "\n…（已截断）"


def fmt_display_time(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        t = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cn = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return cn.strftime("%m-%d %H:%M")
    except Exception:
        return iso_str[:19]


def _extract_markdown_section(body: str, heading_line: str) -> str | None:
    if heading_line not in body:
        return None
    after = body.split(heading_line, 1)[1]
    parts = re.split(r"\n##\s+", after, maxsplit=1)
    text = parts[0].strip()
    return text if text else None


def extract_ai_review_for_card(body: str) -> str:
    """提取「## 总结」段落用于飞书卡片展示。"""
    t = _extract_markdown_section(body, "## 总结")
    return t or "⚠️ AI Review 格式匹配失败，请查看 GitHub 原文"


# GITHUB_TOKEN 发评论时作者一般为 github-actions[bot]；少数环境可能为 github-actions
_GITHUB_ACTIONS_LOGINS = frozenset({"github-actions[bot]", "github-actions"})


def is_claude_ai_comment(_body: str, comment: dict[str, Any] | None = None) -> bool:
    """识别 AI review：仅 GitHub Actions 机器人发帖；排除楼中楼回复。"""
    if not comment or comment.get("in_reply_to_id"):
        return False
    user = comment.get("user") or {}
    if user.get("type") != "Bot":
        return False
    login = (user.get("login") or "").strip().lower()
    return login in _GITHUB_ACTIONS_LOGINS


def _render_pr_open(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    title = ev.get("title", "")
    num = ev.get("pr_number", "")
    author = ev.get("author", "")
    fs = ev.get("file_stat", "")
    return f"📬 **{author}** opened · {tm}\n**{title}** #{num}\n\n{fs}"


def _render_review_requested(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    rq = ev.get("requester", "")
    rv = ev.get("reviewer", "")
    return f"👀 **{rq}** requested **{rv}** · {tm}"


def _render_pr_ready(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    return f"📋 **{ev.get('author', '')}** marked ready for review · {tm}"


def _render_pr_push(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    author = ev.get("author", "")
    n = ev.get("commit_count", 0)
    branch = ev.get("branch", "")
    sha = ev.get("head_sha", "")
    msgs = [str(m).strip() for m in (ev.get("commit_messages") or []) if str(m).strip()]
    head = f"📦 **{author}** pushed **{n}** commit(s) to `{branch}` · {tm}\n"

    if len(msgs) == 1:
        return head + f"**{truncate_text(msgs[0], 200)}** · `{sha}`"
    if len(msgs) > 1:
        first = truncate_text(msgs[0], 200)
        lines = "\n".join(f"- {truncate_text(m, 200)}" for m in msgs[1:8])
        if len(msgs) > 8:
            lines += f"\n- … 共 {len(msgs)} 条说明"
        extra = f"\n{lines}" if lines else ""
        return head + f"**{first}** · `{sha}`{extra}"
    return head + f"`{sha}`"


def _render_pr_reopen(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    return f"🔄 **{ev.get('author', '')}** reopened · {tm}"


def _render_pr_close(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    return f"🚫 **{ev.get('author', '')}** closed · {tm}"


def _render_pr_merge(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    return f"🟢 **{ev.get('merger', '')}** merged · {tm}"


def _render_ai_review(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    body_text = ev.get("final_opinion") or ev.get("summary", "")
    author = ev.get("author", "")
    return f"💬 **{author}** · {tm}\n{body_text}"


def _render_pr_comment(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    author = ev.get("author", "")
    body = ev.get("body", "")
    return f"💬 **{author}** · {tm}\n{body}"


def _render_human_review(ev: dict[str, Any]) -> str:
    tm = fmt_display_time(ev.get("time", ""))
    st = (ev.get("state") or "").lower()
    reviewer = ev.get("reviewer", "")
    body = (ev.get("body") or "").strip()
    if st == "approved":
        head = f"✅ **{reviewer}** approved · {tm}"
    elif st == "changes_requested":
        head = f"❌ **{reviewer}** changes requested · {tm}"
    elif st == "dismissed":
        head = f"⏭ **{reviewer}** dismissed · {tm}"
    else:
        head = f"💬 **{reviewer}** · {tm}"
    if body:
        return f"{head}\n{body}"
    return head


def _render_unknown(ev: dict[str, Any]) -> str:
    t = ev.get("type", "")
    return f"（未知事件 `{t}`）"


_TIMELINE_RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {
    TimelineEventType.PR_OPEN.value: _render_pr_open,
    TimelineEventType.REVIEW_REQUESTED.value: _render_review_requested,
    TimelineEventType.PR_READY.value: _render_pr_ready,
    TimelineEventType.PR_PUSH.value: _render_pr_push,
    TimelineEventType.PR_REOPEN.value: _render_pr_reopen,
    TimelineEventType.PR_CLOSE.value: _render_pr_close,
    TimelineEventType.PR_MERGE.value: _render_pr_merge,
    TimelineEventType.AI_REVIEW.value: _render_ai_review,
    TimelineEventType.PR_COMMENT.value: _render_pr_comment,
    TimelineEventType.HUMAN_REVIEW.value: _render_human_review,
}


def _render_one(ev: dict[str, Any]) -> str:
    t = ev.get("type", "")
    fn = _TIMELINE_RENDERERS.get(t)
    if fn:
        return fn(ev)
    return _render_unknown(ev)


def _trim_events(events: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], bool]:
    kept: list[dict[str, Any]] = []
    total = 0
    omitted = False
    for ev in reversed(events):
        chunk = len(_render_one(ev))
        if kept and total + chunk > budget:
            omitted = True
            break
        kept.append(ev)
        total += chunk
    kept.reverse()
    if len(kept) < len(events):
        omitted = True
    return kept, omitted


def build_timeline_card(record: dict[str, Any]) -> dict:
    repo = record.get("repo", "")
    pr_url = record.get("pr_url", "")
    pr_state = record.get("pr_state", "open")
    events = list(record.get("events") or [])

    template = TYPE_TEMPLATE.get(pr_state, "red")
    state_label = PR_STATE_HEADER_EN.get(pr_state, pr_state.capitalize())
    header_title = truncate_text(f"{repo} · {state_label}", 200)

    trimmed, omitted = _trim_events(events, MAX_TIMELINE_CHARS)
    elements: list[dict[str, Any]] = []

    if omitted:
        n = len(events) - len(trimmed)
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"⏱ 较早 **{n}** 条事件已省略展示，完整记录见 GitHub。",
                },
            }
        )
        elements.append({"tag": "hr"})

    for i, ev in enumerate(trimmed):
        if i > 0:
            elements.append({"tag": "hr"})
        text = truncate_text(_render_one(ev), MAX_SINGLE_EVENT_CHARS)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": text}})

    elements.append(
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"content": "查看 PR", "tag": "plain_text"},
                    "type": "primary",
                    "url": pr_url,
                }
            ],
        }
    )

    return {
        "header": {"template": template, "title": {"content": header_title, "tag": "plain_text"}},
        "elements": elements,
    }
