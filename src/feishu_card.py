# -*- coding: utf-8 -*-
"""飞书时间线卡片：从 PR 记录构建 interactive 卡片"""

from __future__ import annotations

import re
from typing import Any

TYPE_TEMPLATE = {"open": "blue", "merged": "green", "closed": "grey"}

MAX_SINGLE_EVENT_CHARS = 2000
MAX_TIMELINE_CHARS = 22000
MAX_ISSUE_COMMENT_BODY = 100


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
        from datetime import datetime

        t = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
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


def is_claude_ai_comment(body: str) -> bool:
    if "## AI Code Review 总结" in body:
        return True
    if "## 最终意见" in body:
        return True
    if "🤖" in body and "Claude" in body:
        return True
    return False


def _render_one(ev: dict[str, Any]) -> str:
    t = ev.get("type", "")
    tm = fmt_display_time(ev.get("time", ""))

    if t == "pr_open":
        title = ev.get("title", "")
        num = ev.get("pr_number", "")
        author = ev.get("author", "")
        fs = ev.get("file_stat", "")
        return (
            f"📬 **{author}** opened · {tm}\n**{title}** #{num}\n\n{fs}"
        )

    if t == "pr_push":
        author = ev.get("author", "")
        n = ev.get("commit_count", 0)
        branch = ev.get("branch", "")
        sha = ev.get("head_sha", "")
        msgs = ev.get("commit_messages") or []
        extra = ""
        if msgs:
            lines = "\n".join(f"- {truncate_text(m, 200)}" for m in msgs[:8])
            if len(msgs) > 8:
                lines += f"\n- … 共 {len(msgs)} 条说明"
            extra = f"\n{lines}"
        return f"📦 **{author}** pushed **{n}** commit(s) to `{branch}` · {tm}\nHEAD: `{sha}`{extra}"

    if t == "pr_reopen":
        return f"🔄 **{ev.get('author', '')}** reopened · {tm}"

    if t == "pr_close":
        return f"🚫 **{ev.get('author', '')}** closed · {tm}"

    if t == "pr_merge":
        return f"🟢 **{ev.get('merger', '')}** merged · {tm}"

    if t == "ai_review":
        body_text = ev.get("final_opinion") or ev.get("summary", "")
        author = ev.get("author", "")
        return f"🤖 **Claude AI Review · 最终意见**（{author}）· {tm}\n{body_text}"

    if t == "pr_comment":
        author = ev.get("author", "")
        body = ev.get("body", "")
        return f"💬 **{author}** commented · {tm}\n{body}"

    if t == "human_review":
        st = (ev.get("state") or "").lower()
        reviewer = ev.get("reviewer", "")
        body = (ev.get("body") or "").strip()
        if st == "approved":
            head = f"✅ **{reviewer}** approved · {tm}"
        elif st == "changes_requested":
            head = f"❌ **{reviewer}** requested changes · {tm}"
        elif st == "dismissed":
            head = f"⏭ **{reviewer}** review dismissed · {tm}"
        else:
            head = f"💬 **{reviewer}** reviewed · {tm}"
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
    title = record.get("pr_title", "")
    pr_url = record.get("pr_url", "")
    pr_state = record.get("pr_state", "open")
    events = list(record.get("events") or [])

    template = TYPE_TEMPLATE.get(pr_state, "blue")
    header_title = truncate_text(f"{repo}: {title}", 200)

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
