# -*- coding: utf-8 -*-
"""飞书时间线卡片：从 PR 记录构建 interactive 卡片"""

from __future__ import annotations

import re
from typing import Any

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


def extract_ai_review_for_card(body: str) -> str | None:
    """飞书卡片展示：优先「最终意见」，否则回退「AI Code Review 总结」（兼容旧格式）。"""
    t = _extract_markdown_section(body, "## 最终意见")
    if t:
        return t
    return _extract_markdown_section(body, "## AI Code Review 总结")


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


def _render_one(ev: dict[str, Any]) -> str:
    t = ev.get("type", "")
    tm = fmt_display_time(ev.get("time", ""))

    if t == "pr_open":
        title = ev.get("title", "")
        num = ev.get("pr_number", "")
        author = ev.get("author", "")
        fs = ev.get("file_stat", "")
        req = ev.get("requested_reviewers") or []
        block = f"📬 **{author}** opened · {tm}\n**{title}** #{num}\n\n{fs}"
        if req:
            block += f"\n\n👀 Review: {', '.join(req)}"
        return block

    if t == "review_requested":
        rq = ev.get("requester", "")
        rv = ev.get("reviewer", "")
        return f"👀 **{rq}** requested **{rv}** · {tm}"

    if t == "pr_push":
        author = ev.get("author", "")
        n = ev.get("commit_count", 0)
        branch = ev.get("branch", "")
        sha = ev.get("head_sha", "")
        msgs = ev.get("commit_messages") or []
        head_line = f"HEAD: `{sha}`"
        if len(msgs) == 1:
            head_line = f"HEAD: `{sha}`  ·  **{truncate_text(msgs[0], 200)}**"
            extra = ""
        elif msgs:
            lines = "\n".join(f"- {truncate_text(m, 200)}" for m in msgs[:8])
            if len(msgs) > 8:
                lines += f"\n- … 共 {len(msgs)} 条说明"
            extra = f"\n{lines}"
        else:
            extra = ""
        return f"📦 **{author}** pushed **{n}** commit(s) to `{branch}` · {tm}\n{head_line}{extra}"

    if t == "pr_reopen":
        return f"🔄 **{ev.get('author', '')}** reopened · {tm}"

    if t == "pr_close":
        return f"🚫 **{ev.get('author', '')}** closed · {tm}"

    if t == "pr_merge":
        return f"🟢 **{ev.get('merger', '')}** merged · {tm}"

    if t == "ai_review":
        body_text = ev.get("final_opinion") or ev.get("summary", "")
        author = ev.get("author", "")
        return f"💬 **{author}** · {tm}\n{body_text}"

    if t == "pr_comment":
        author = ev.get("author", "")
        body = ev.get("body", "")
        return f"💬 **{author}** · {tm}\n{body}"

    if t == "human_review":
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

    return f"（未知事件 `{t}`）"


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
