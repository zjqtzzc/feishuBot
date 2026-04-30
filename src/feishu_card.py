# -*- coding: utf-8 -*-
"""飞书时间线卡片：从 PR 记录构建 interactive 卡片"""

from __future__ import annotations

import re
from typing import Any, Callable

from src.timeline_event_type import TimelineEventType

# 渲染函数签名: (event_dict, feishu_map_or_none) -> str
Renderer = Callable[[dict[str, Any], dict[str, str] | None], str]

# 卡片模板颜色映射
# 用于根据 PR 状态设置卡片头部颜色
TYPE_TEMPLATE = {"open": "red", "merged": "green", "closed": "grey"}

# PR 状态头部英文标签
# 与 handlers.pr_state_from_payload 一致，共 3 种状态
PR_STATE_HEADER_EN = {"open": "Open", "merged": "Merged", "closed": "Closed"}

# 单个事件的最大字符数
# 超过此限制的事件内容会被截断
MAX_SINGLE_EVENT_CHARS = 2000

# 整个时间线的最大字符数
# 超过此限制的事件会被省略
MAX_TIMELINE_CHARS = 22000

# Issue 评论正文的最大字符数
# 超过此限制的评论会被截断
MAX_ISSUE_COMMENT_BODY = 100

# GitHub Actions 机器人登录名
# GITHUB_TOKEN 发评论时作者一般为 github-actions[bot]；少数环境可能为 github-actions
GITHUB_ACTIONS_LOGINS = frozenset({"github-actions[bot]", "github-actions"})


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


def _fmt_user(name: str, fm: dict[str, str] | None = None) -> str:
    """渲染用户名：有飞书映射则用 @mention，否则回退粗体。"""
    if not name:
        return ""
    fm = fm or {}
    fid = fm.get(name)
    if fid:
        return f"<at id={fid}>{name}</at>"
    return f"**{name}**"


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



def is_claude_ai_comment(_body: str, comment: dict[str, Any] | None = None) -> bool:
    """识别 AI review：仅 GitHub Actions 机器人发帖；排除楼中楼回复。"""
    if not comment or comment.get("in_reply_to_id"):
        return False
    user = comment.get("user") or {}
    if user.get("type") != "Bot":
        return False
    login = (user.get("login") or "").strip().lower()
    return login in GITHUB_ACTIONS_LOGINS


def _render_user_action(ev: dict[str, Any], action: str, fm: dict[str, str] | None = None, user_key: str = "author") -> str:
    user = ev.get(user_key, "")
    return f"**{user}** {action}"


def _render_with_content(ev: dict[str, Any], content_key: str, fm: dict[str, str] | None = None, author_key: str = "author") -> str:
    author = ev.get(author_key, "")
    content = ev.get(content_key, "")
    return f"**{author}**\n{content}"


def _render_pr_open(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    title = ev.get("title", "")
    num = ev.get("pr_number", "")
    author = ev.get("author", "")
    fs = ev.get("file_stat", "")
    base = f"**{author}** opened\n**{title}** #{num}"
    return f"{base}\n{fs}" if fs else base


def _render_review_requested(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    rq = ev.get("requester", "")
    rv = ev.get("reviewer", "")
    return f"**{rq}** requested {_fmt_user(rv, fm)}"


def _render_pr_ready(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    return _render_user_action(ev, "marked ready for review", fm)


def _render_pr_push(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    author = ev.get("author", "")
    n = ev.get("commit_count", 0)
    branch = ev.get("branch", "")
    msgs = [str(m).strip() for m in (ev.get("commit_messages") or []) if str(m).strip()]
    head = f"**{author}** pushed **{n}** commit(s) to `{branch}`"
    return f"{head}\n{truncate_text(msgs[0], 150)}" if msgs else head


def _render_pr_reopen(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    return _render_user_action(ev, "reopened", fm)


def _render_pr_close(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    return _render_user_action(ev, "closed", fm)


def _render_pr_merge(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    return _render_user_action(ev, "merged", fm, user_key="merger")


def _render_ai_review(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    body_text = ev.get("final_opinion") or ev.get("summary", "")
    author = ev.get("author", "")
    return f"**{author}**\n{body_text}"


def _render_pr_comment(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    return _render_with_content(ev, "body", fm)


def _render_human_review(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    st = (ev.get("state") or "").lower()
    reviewer = ev.get("reviewer", "")
    body = (ev.get("body") or "").strip()

    action_map = {
        "approved": "approved",
        "changes_requested": "changes requested",
        "dismissed": "dismissed"
    }

    action = action_map.get(st, "")
    head = f"{_fmt_user(reviewer, fm)}{f' {action}' if action else ''}"
    return f"{head}\n{body}" if body else head


def _render_unknown(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    t = ev.get("type", "")
    return f"（未知事件 `{t}`）"


_TIMELINE_RENDERERS: dict[str, Renderer] = {
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


def _render_one(ev: dict[str, Any], fm: dict[str, str] | None = None) -> str:
    t = ev.get("type", "")
    fn = _TIMELINE_RENDERERS.get(t)
    if fn:
        return fn(ev, fm)
    return _render_unknown(ev, fm)


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


def build_timeline_card(record: dict[str, Any], feishu_map: dict[str, str] | None = None) -> dict:
    repo = record.get("repo", "")
    pr_url = record.get("pr_url", "")
    pr_state = record.get("pr_state", "open")
    events = record.get("events") or []
    fm = feishu_map or {}

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
        text = truncate_text(_render_one(ev, fm), MAX_SINGLE_EVENT_CHARS)
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
