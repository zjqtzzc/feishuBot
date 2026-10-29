# -*- coding: utf-8 -*-
"""飞书状态卡片（卡片 JSON 2.0）：根据 GitHub 当前的 PR / reviews / 评论生成 interactive 卡片"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

# 状态 → (头部标签文案, 标签颜色, 头部颜色)
STATE_STYLE = {
    "open": ("Open", "red", "red"),
    "draft": ("Draft", "neutral", "grey"),
    "merged": ("Merged", "green", "green"),
    "closed": ("Closed", "neutral", "grey"),
}

# GitHub Actions 机器人登录名：AI review 由它以 issue comment 发出
GITHUB_ACTIONS_LOGINS = frozenset({"github-actions[bot]", "github-actions"})

AI_FORMAT_ERROR = "AI Review 格式匹配失败，请查看 GitHub 原文"

CST = timezone(timedelta(hours=8))

# 改动文件明细最多展示的行数
MAX_FILE_GROUPS = 8

# 不计入 CI 的检查（名字小写包含即排除）：AI review 已单独显示
CI_EXCLUDE = ("ai-review",)
CI_FAILED = frozenset({"failure", "timed_out", "startup_failure", "action_required"})
CI_WAITING = frozenset({"queued", "waiting", "pending", "requested"})


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


def _group_files(files: list[dict[str, Any]], depth: int) -> dict[str, list[int]]:
    """按前 depth 层路径分组：{路径: [增, 删, 文件数]}。目录以 / 结尾，层级不足的文件用完整路径。"""
    out: dict[str, list[int]] = {}
    for f in files:
        parts = (f.get("filename") or "").split("/")
        key = "/".join(parts[:depth]) + "/" if len(parts) > depth else "/".join(parts)
        g = out.setdefault(key, [0, 0, 0])
        g[0] += f.get("additions", 0)
        g[1] += f.get("deletions", 0)
        g[2] += 1
    return out


def summarize_files(files: list[dict[str, Any]]) -> list[tuple[str, int, int, int]]:
    """改动文件按目录汇总，返回 [(路径, 增, 删, 文件数)]，按路径排序。

    从第 2 层开始，取第一个能分出 2 组以上的层级；超过 MAX_FILE_GROUPS 时，
    保留改动最多的几组，其余合并为「其他 N 项」放在最后。
    """
    if not files:
        return []
    max_depth = max(len((f.get("filename") or "").split("/")) for f in files)
    depth = next((d for d in range(2, max_depth + 1) if len(_group_files(files, d)) > 1), max_depth)
    rows = [(k, *v) for k, v in _group_files(files, depth).items()]
    other = None
    if len(rows) > MAX_FILE_GROUPS:
        rows.sort(key=lambda r: -(r[1] + r[2]))
        rest = rows[MAX_FILE_GROUPS - 1:]
        rows = rows[: MAX_FILE_GROUPS - 1]
        other = (f"其他 {len(rest)} 项", sum(r[1] for r in rest), sum(r[2] for r in rest), sum(r[3] for r in rest))
    rows.sort(key=lambda r: r[0])
    return rows + ([other] if other else [])


def _short_path(path: str) -> str:
    """超过 3 层时只保留第一层和最后一段：a/b/c/d/ → a/…/d/，保证一行放得下"""
    is_dir = path.endswith("/")
    parts = path.rstrip("/").split("/")
    if len(parts) > 3:
        parts = [parts[0], "…", parts[-1]]
    return "/".join(parts) + ("/" if is_dir else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _file_row(path: str, adds: int, dels: int, count: int) -> dict:
    """一行改动：左栏路径，右栏文件数（多于 1 个时）和增删，分栏保证各行数字对齐。"""
    name = path if path.startswith("其他 ") else _short_path(path)
    stat = f"<font color='green'>+{adds}</font> <font color='red'>-{dels}</font>"
    if count > 1:
        stat = f"{_grey(f'{count} files')}  {stat}"
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "horizontal_spacing": "8px",
        "columns": [
            {"tag": "column", "width": "weighted", "weight": 4,
             "elements": [{"tag": "markdown", "content": _grey(name), "text_size": "notation"}]},
            {"tag": "column", "width": "auto",
             "elements": [{"tag": "markdown", "content": stat, "text_size": "notation", "text_align": "right"}]},
        ],
    }


def _files_panel(pr: dict[str, Any], files: list[dict[str, Any]] | None, errors: dict[str, int]) -> dict:
    """折叠面板：标题为改动合计，展开后每个目录一行。"""
    title = (
        f"{_plural(pr.get('changed_files', 0), 'file')} <font color='green'>+{pr.get('additions', 0)}</font> "
        f"<font color='red'>-{pr.get('deletions', 0)}</font> · {_plural(pr.get('commits', 0), 'commit')}"
    )
    if files is None:
        rows = [_markdown([_no_access("改动文件", errors.get("files") or errors.get("pr", 0))], "notation")]
    elif not files:
        rows = [_markdown([_grey("没有改动文件")], "notation")]
    else:
        rows = [_file_row(*row) for row in summarize_files(files)]
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "vertical_spacing": "2px",
        "header": {
            "title": {"tag": "markdown", "content": title},
            "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "size": "16px 16px"},
            "icon_position": "follow_text",
            "icon_expanded_angle": -180,
        },
        "elements": rows,
    }


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, CST).strftime("%m-%d %H:%M")


def _parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def _ci_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in runs if not any(x in (r.get("name") or "").lower() for x in CI_EXCLUDE)]


def failed_ci_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((r for r in _ci_runs(runs) if r.get("conclusion") in CI_FAILED), None)


def failed_step_name(job: dict[str, Any]) -> str | None:
    return next((s.get("name") for s in job.get("steps") or [] if s.get("conclusion") == "failure"), None)


def _duration(run: dict[str, Any]) -> str:
    start, end = _parse_iso(run.get("started_at")), _parse_iso(run.get("completed_at"))
    if not start or not end:
        return ""
    minutes = round((end - start) / 60)
    if minutes < 60:
        return f"用时 {max(minutes, 1)} 分钟"
    return f"用时 {minutes // 60} 小时 {minutes % 60} 分钟"


def _ci_line(runs: list[dict[str, Any]] | None, failed_step: str | None, errors: dict[str, int]) -> str:
    """CI 状态一行。runs 为 None 表示无权限读取；没有 CI（如 PR 不针对 develop）时返回空串。"""
    if runs is None:
        return _no_access(" CI 状态", errors.get("ci", 0))
    runs = _ci_runs(runs)
    if not runs:
        return ""
    many = len(runs) > 1
    failed = [r for r in runs if r.get("conclusion") in CI_FAILED]
    if failed:
        r = failed[0]
        name = f"{r.get('name')} " if many else ""
        if "ci_steps" in errors:
            where = name + _no_access("失败步骤", errors["ci_steps"])
        else:
            where = f"{name}失败于「{failed_step}」" if failed_step else name.strip()
        parts = [p for p in (f"{len(failed)}/{len(runs)} 失败" if many else "", where, _duration(r)) if p]
        parts.append(f"[查看日志]({r.get('html_url', '')})")
        return f"{_tag('CI 失败', 'red')} " + " · ".join(parts)
    running = [r for r in runs if r.get("status") == "in_progress"]
    if running:
        start = _parse_iso(running[0].get("started_at"))
        return f"{_tag('CI 运行中', 'blue')} " + (_grey(f"{_fmt_time(start)} 开始") if start else "")
    waiting = [r for r in runs if r.get("status") in CI_WAITING]
    if waiting:
        start = _parse_iso(waiting[0].get("started_at"))
        return f"{_tag('CI 排队中', 'neutral')} " + (_grey(f"{_fmt_time(start)} 开始排队") if start else "")
    if any(r.get("conclusion") == "cancelled" for r in runs):
        return _tag("CI 已取消", "neutral")
    longest = max(runs, key=lambda r: (_parse_iso(r.get("completed_at")) or 0) - (_parse_iso(r.get("started_at")) or 0))
    return f"{_tag('CI 通过', 'green')} " + _grey(_duration(longest))


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
    files: list[dict[str, Any]] | None = None,
    ci_runs: list[dict[str, Any]] | None = (),
    ci_failed_step: str | None = None,
) -> dict:
    """reviews / comments / files / ci_runs 为 None 表示无权限读取；errors 记录读取失败部分的 HTTP 状态码。

    头部：PR 标题，副标题「仓库 #号 · 作者」，状态标签。
    正文：reviewer、AI 结论、CI 状态；折叠面板（标题为改动合计，展开为按目录汇总的改动文件）；
    底部小号字：分支、评论数、最近动态；「查看 PR」按钮。
    合并/关闭后只剩一行小号字，末尾为「查看 PR」链接。
    """
    fm = feishu_map or {}
    errors = errors or {}
    state = pr_state(pr)
    url = pr.get("html_url", "")
    title = pr.get("title", "")
    author = (pr.get("user") or {}).get("login", "")
    label, tag_color, template = STATE_STYLE[state]

    ai = [c for c in comments or [] if is_ai_comment(c)]
    human_comments = len(comments or []) - len(ai)

    main: list[str] = []
    meta: list[str] = []
    if state in ("merged", "closed"):
        who = f"{(pr.get('merged_by') or {}).get('login', '')} merged" if state == "merged" else "Closed"
        parts = [who, _plural(pr.get("commits", 0), "commit")]
        if ai:
            parts.append(f"AI review {len(ai)} 轮")
        meta.append(f"{_grey(' · '.join(parts))} · [查看 PR]({url})")
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
        ci_line = _ci_line(ci_runs, ci_failed_step, errors)
        if ci_line:
            main.append(ci_line)

        head = (pr.get("head") or {}).get("ref", "")
        base = (pr.get("base") or {}).get("ref", "")
        tail = [f"{head} → {base}"]
        if human_comments:
            tail.append(f"{human_comments} 条评论")
        if activity and activity.get("text"):
            tail.append(f"最近 {activity['text']} · {_fmt_time(activity['at'])}")
        meta.append(_grey(" · ".join(tail)))

    elements = []
    if main:
        elements.append(_markdown(main))
    if state not in ("merged", "closed"):
        elements.append(_files_panel(pr, files, errors))
    elements.append(_markdown(meta, "notation"))
    if state not in ("merged", "closed"):
        elements.append(
            {
                "tag": "button",
                "type": "primary",
                "text": {"tag": "plain_text", "content": "查看 PR"},
                "behaviors": [{"type": "open_url", "default_url": url}],
            }
        )

    return {
        "schema": "2.0",
        # 更新卡片接口要求更新前后的卡片都声明为共享卡片
        "config": {"update_multi": True, "summary": {"content": f"[{label}] {title}"}},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": f"{repo.split('/')[-1]} #{pr.get('number')} · {author}"},
            "text_tag_list": [{"tag": "text_tag", "text": {"tag": "plain_text", "content": label}, "color": tag_color}],
        },
        "body": {"elements": elements},
    }
