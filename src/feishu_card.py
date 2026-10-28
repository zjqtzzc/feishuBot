# -*- coding: utf-8 -*-
"""飞书状态卡片：根据 GitHub 当前的 PR / reviews / 评论生成 interactive 卡片"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

# 卡片头部颜色
TEMPLATE = {"open": "red", "draft": "grey", "merged": "green", "closed": "grey"}

# GitHub Actions 机器人登录名：AI review 由它以 issue comment 发出
GITHUB_ACTIONS_LOGINS = frozenset({"github-actions[bot]", "github-actions"})

AI_FORMAT_ERROR = "AI Review 格式匹配失败，请查看 GitHub 原文"

CST = timezone(timedelta(hours=8))


def truncate_text(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _fmt_user(name: str, fm: dict[str, str]) -> str:
    """有飞书映射则 @mention，否则粗体。"""
    fid = fm.get(name)
    return f"<at id={fid}>{name}</at>" if fid else f"**{name}**"


def is_ai_comment(comment: dict[str, Any]) -> bool:
    user = comment.get("user") or {}
    if user.get("type") != "Bot":
        return False
    return (user.get("login") or "").strip().lower() in GITHUB_ACTIONS_LOGINS


def _extract_markdown_section(body: str, heading_line: str) -> str | None:
    if heading_line not in body:
        return None
    after = body.split(heading_line, 1)[1]
    text = re.split(r"\n##\s+", after, maxsplit=1)[0].strip()
    return text or None


def ai_conclusion(body: str) -> str:
    """取「## 总结」段落里的「结论：」一行。"""
    section = _extract_markdown_section(body, "## 总结")
    if not section:
        return AI_FORMAT_ERROR
    m = re.search(r"结论\**\s*[：:]\s*\**\s*(.+)", section)
    return truncate_text(m.group(1) if m else section, 200)


def pr_state(pr: dict[str, Any]) -> str:
    if pr.get("merged"):
        return "merged"
    if pr.get("state") == "closed":
        return "closed"
    return "draft" if pr.get("draft") else "open"


def _no_access(what: str, status: int) -> str:
    return f"<font color='red'>无法读取{what}（HTTP {status}，请检查 GitHub token 权限）</font>"


def _review_line(pr: dict[str, Any], reviews: list[dict[str, Any]] | None, fm: dict[str, str]) -> str:
    verdict: dict[str, str] = {}
    for rv in reviews or []:
        user = (rv.get("user") or {}).get("login", "")
        st = (rv.get("state") or "").upper()
        if st in ("APPROVED", "CHANGES_REQUESTED"):
            verdict[user] = st
        elif st == "DISMISSED":
            verdict.pop(user, None)
    pending = [u.get("login", "") for u in pr.get("requested_reviewers") or []]
    pending = [u for u in pending if u not in verdict]
    teams = [f"team/{t.get('slug') or t.get('name')}" for t in pr.get("requested_teams") or []]

    parts = [f"{_fmt_user(u, fm)} 待审" for u in pending]
    parts += [f"**{t}** 待审" for t in teams]
    # 已给出结论的 reviewer 不再 @
    parts += [f"**{u}** {'approved' if st == 'APPROVED' else 'requested changes'}" for u, st in verdict.items()]
    return " · ".join(parts)


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, CST).strftime("%m-%d %H:%M")


def build_status_card(
    pr: dict[str, Any],
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    activity: dict[str, Any] | None,
    repo: str,
    feishu_map: dict[str, str] | None = None,
    errors: dict[str, int] | None = None,
) -> dict:
    """reviews / comments 为 None 表示无权限读取；errors 记录读取失败部分的 HTTP 状态码。"""
    fm = feishu_map or {}
    errors = errors or {}
    state = pr_state(pr)
    number = pr.get("number")
    url = pr.get("html_url", "")
    title = f"{'[Draft] ' if state == 'draft' else ''}{pr.get('title', '')} #{number}"

    ai = [c for c in comments or [] if is_ai_comment(c)]
    human_comments = len(comments or []) - len(ai)

    if state in ("merged", "closed"):
        if state == "merged":
            who = f"**{(pr.get('merged_by') or {}).get('login', '')}** merged"
        else:
            who = "Closed"
        parts = [repo, who, f"{pr.get('commits', 0)} commits"]
        if ai:
            parts.append(f"AI review {len(ai)} 轮")
        if errors:
            parts.append(_no_access("部分信息", next(iter(errors.values()))))
        lines = [" · ".join(parts) + f" · [查看 PR]({url})"]
        actions = []
    else:
        head = (pr.get("head") or {}).get("ref", "")
        base = (pr.get("base") or {}).get("ref", "")
        author = (pr.get("user") or {}).get("login", "")
        lines = []
        if "pr" in errors:
            lines.append(_no_access(" PR 最新状态", errors["pr"]) + "，以下为事件中的数据")
        lines.append(f"{repo} · **{author}** · `{head}` → `{base}`")
        if "changed_files" in pr:
            lines.append(
                f"{pr['changed_files']} files "
                f"<font color='green'>+{pr.get('additions', 0)}</font> "
                f"<font color='red'>-{pr.get('deletions', 0)}</font> · {pr.get('commits', 0)} commits"
            )
        else:
            lines.append(_no_access("改动统计", errors.get("pr", 0)))
        review_line = _review_line(pr, reviews, fm)
        if reviews is None:
            warn = _no_access(" reviews", errors.get("reviews", 0))
            review_line = f"{review_line} · {warn}" if review_line else warn
        if review_line:
            lines.append(f"Reviewers：{review_line}")
        if comments is None:
            lines.append(_no_access("评论和 AI review", errors.get("comments", 0)))
        if ai:
            lines.append(f"AI 第 {len(ai)} 轮：{ai_conclusion(ai[-1].get('body') or '')}")
        if human_comments:
            lines.append(f"{human_comments} 条评论")
        if activity and activity.get("text"):
            lines.append(f"最近：{activity['text']} · {_fmt_time(activity['at'])}")
        actions = [
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"content": "查看 PR", "tag": "plain_text"},
                        "type": "primary",
                        "url": url,
                    }
                ],
            }
        ]

    return {
        "header": {
            "template": TEMPLATE[state],
            "title": {"content": truncate_text(title, 200), "tag": "plain_text"},
        },
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}, *actions],
    }
