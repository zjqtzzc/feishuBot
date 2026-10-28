# -*- coding: utf-8 -*-
"""飞书状态卡片（卡片 JSON 2.0）：根据 GitHub 当前的 PR / reviews / 评论生成 interactive 卡片"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

# 卡片头部颜色
TEMPLATE = {"open": "red", "draft": "grey", "merged": "green", "closed": "grey"}
# 头部状态标签：(文案, 颜色)
STATE_TAG = {
    "open": ("Open", "red"),
    "draft": ("Draft", "neutral"),
    "merged": ("Merged", "green"),
    "closed": ("Closed", "neutral"),
}

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
    return f"<at id={fid}></at>" if fid else f"**{name}**"


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


def _tag(text: str, color: str) -> str:
    return f"<text_tag color='{color}'>{text}</text_tag>"


def _grey(text: str) -> str:
    return f"<font color='grey'>{text}</font>"


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

    waiting = _tag("待审", "orange")
    parts = [f"{waiting} {_fmt_user(u, fm)}" for u in pending]
    parts += [f"{waiting} **{t}**" for t in teams]
    # 已给出结论的 reviewer 不再 @
    for u, st in verdict.items():
        tag = _tag("通过", "green") if st == "APPROVED" else _tag("要求修改", "red")
        parts.append(f"{tag} **{u}**")
    return "  ".join(parts)


def _ai_line(ai: list[dict[str, Any]]) -> str:
    conclusion = ai_conclusion(ai[-1].get("body") or "")
    if conclusion == AI_FORMAT_ERROR:
        tag = _tag("AI", "neutral")
    elif re.search(r"不可接受|不通过", conclusion):
        tag = _tag("AI 不通过", "red")
    elif re.search(r"可以?接受|通过", conclusion):
        tag = _tag("AI 通过", "green")
    else:
        tag = _tag("AI", "neutral")
    return f"{tag} {conclusion} {_grey(f'第 {len(ai)} 轮')}"


def _stat_line(pr: dict[str, Any], errors: dict[str, int]) -> str:
    head = (pr.get("head") or {}).get("ref", "")
    base = (pr.get("base") or {}).get("ref", "")
    branch = _grey(f"{head} → {base}")
    if "changed_files" not in pr:
        return f"{branch} {_no_access('改动统计', errors.get('pr', 0))}"
    files = _grey(f"· {pr['changed_files']} files")
    adds = f"<font color='green'>+{pr.get('additions', 0)}</font>"
    dels = f"<font color='red'>-{pr.get('deletions', 0)}</font>"
    commits = pr.get("commits", 0)
    return f"{branch} {files} {adds} {dels} {_grey(f'· {commits} commits')}"


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, CST).strftime("%m-%d %H:%M")


def _markdown(lines: list[str], text_size: str = "normal") -> dict:
    return {"tag": "markdown", "content": "\n".join(lines), "text_size": text_size}


def build_status_card(
    pr: dict[str, Any],
    reviews: list[dict[str, Any]] | None,
    comments: list[dict[str, Any]] | None,
    activity: dict[str, Any] | None,
    repo: str,
    feishu_map: dict[str, str] | None = None,
    errors: dict[str, int] | None = None,
) -> dict:
    """reviews / comments 为 None 表示无权限读取；errors 记录读取失败部分的 HTTP 状态码。

    头部：PR 标题，副标题「仓库 #号 · 作者」，状态标签。
    正文：reviewer 与 AI 结论。底部小号字：分支、改动统计、评论数、最近动态。
    整张卡片点击跳转 PR。
    """
    fm = feishu_map or {}
    errors = errors or {}
    state = pr_state(pr)
    title = pr.get("title", "")
    author = (pr.get("user") or {}).get("login", "")
    label, tag_color = STATE_TAG[state]

    ai = [c for c in comments or [] if is_ai_comment(c)]
    human_comments = len(comments or []) - len(ai)

    main: list[str] = []
    meta: list[str] = []
    if state in ("merged", "closed"):
        who = f"{(pr.get('merged_by') or {}).get('login', '')} merged" if state == "merged" else "Closed"
        parts = [who, f"{pr.get('commits', 0)} commits"]
        if ai:
            parts.append(f"AI review {len(ai)} 轮")
        meta.append(_grey(" · ".join(parts)))
        if errors:
            meta.append(_no_access("部分信息", next(iter(errors.values()))))
    else:
        if "pr" in errors:
            main.append(_no_access(" PR 最新状态", errors["pr"]) + "，以下为事件中的数据")
        review_line = _review_line(pr, reviews, fm)
        if reviews is None:
            warn = _no_access(" reviews", errors.get("reviews", 0))
            review_line = f"{review_line}  {warn}" if review_line else warn
        if review_line:
            main.append(review_line)
        if comments is None:
            main.append(_no_access("评论和 AI review", errors.get("comments", 0)))
        if ai:
            main.append(_ai_line(ai))

        meta.append(_stat_line(pr, errors))
        tail = []
        if human_comments:
            tail.append(f"{human_comments} 条评论")
        if activity and activity.get("text"):
            tail.append(f"最近 {activity['text']} · {_fmt_time(activity['at'])}")
        if tail:
            meta.append(_grey(" · ".join(tail)))

    elements = []
    if main:
        elements.append(_markdown(main))
    elements.append(_markdown(meta, "notation"))

    return {
        "schema": "2.0",
        # 更新卡片接口要求更新前后的卡片都声明为共享卡片
        "config": {"update_multi": True, "summary": {"content": f"[{label}] {title}"}},
        "card_link": {"url": pr.get("html_url", "")},
        "header": {
            "template": TEMPLATE[state],
            "title": {"tag": "plain_text", "content": truncate_text(title, 200)},
            "subtitle": {"tag": "plain_text", "content": f"{repo.split('/')[-1]} #{pr.get('number')} · {author}"},
            "text_tag_list": [{"tag": "text_tag", "text": {"tag": "plain_text", "content": label}, "color": tag_color}],
        },
        "body": {"elements": elements},
    }
