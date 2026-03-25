import os
import subprocess
import requests

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GITHUB_TOKEN      = os.environ["GITHUB_TOKEN"]
REPO              = os.environ["REPO"]
PR_NUMBER         = os.environ["PR_NUMBER"]
BASE_SHA          = os.environ["BASE_SHA"]
HEAD_SHA          = os.environ["HEAD_SHA"]

SKIP_PATTERNS = [".env", "secret", "lock", ".min.js", ".min.css",
                 "package-lock.json", "yarn.lock", "poetry.lock"]

MAX_DIFF_CHARS = 12000
AI_REVIEW_MARKER = "🤖 **Claude AI Review**"

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

PROJECT_CONTEXT = """项目背景：C++17 自动洗车机器人系统，使用 Apollo Cyber RT（类 ROS 事件驱动框架）通信，Vue 3 前端。
四臂机器人平台，主要依赖 Eigen3、Pinocchio（运动学）、FCL（碰撞检测）、ruckig（轨迹）。
命名规范：类 CamelCase，函数 camelBack，私有成员 _ 后缀，宏 UPPER_CASE。"""

REVIEW_FORMAT = """输出严格使用以下两个标题，不要增设其他标题或小节：

## 总结
（内容）

## 问题
每条问题用 `- 🔴`/`- 🟡`/`- 🟢` 开头（🔴 阻塞 / 🟡 建议 / 🟢 nit），一条一个 `-`。
无问题则只写"无"。"""

SYSTEM_PROMPT = f"""你是一个专业代码 reviewer，使用中文。

{PROJECT_CONTEXT}

重点关注：
- 潜在的 bug 或逻辑错误
- 安全风险（空指针/悬垂引用、数组越界、多线程竞争、浮点 NaN 传播等）
- 明显的性能问题
- 代码可读性和命名规范

{REVIEW_FORMAT}

「总结」：1～2 句概括修改内容，1～2 句说明能否接受及理由。
「问题」：简单问题 1～2 行；复杂问题可 4～6 行。同类只写一次。

保持简洁，不要复述 diff 内容。"""

INCREMENTAL_SYSTEM_PROMPT = f"""你是一个专业代码 reviewer，正在对 PR 的后续提交做增量 review，使用中文。

{PROJECT_CONTEXT}

你会收到之前的评论历史和本次新增的 diff。重点判断：
- 之前指出的问题是否已修复
- 新代码是否引入了新的 bug、安全或性能问题

{REVIEW_FORMAT}

「总结」：1～2 句说明之前的问题是否解决，整体是否可接受。
「问题」：仅列未修复的旧问题和新引入的问题，已解决的不再提及。无问题则写"无"。

尽量简短。"""


def get_diff():
    if not BASE_SHA or not HEAD_SHA:
        raise RuntimeError(f"BASE_SHA 或 HEAD_SHA 为空，BASE_SHA={BASE_SHA!r}, HEAD_SHA={HEAD_SHA!r}")

    # 用 merge-base 找到 PR 分支真正的分叉点，避免把目标分支上其他 PR 的改动也算进来
    proc = subprocess.run(
        ["git", "merge-base", BASE_SHA, HEAD_SHA],
        capture_output=True, text=True, check=True
    )
    merge_base = proc.stdout.strip()
    if not merge_base:
        raise RuntimeError(f"git merge-base 返回空，BASE_SHA={BASE_SHA}, HEAD_SHA={HEAD_SHA}")
    print(f"merge_base: {merge_base}")

    result = subprocess.run(
        ["git", "diff", merge_base, HEAD_SHA],
        capture_output=True, text=True, check=True
    )
    filtered_lines = []
    skip = False
    for line in result.stdout.splitlines():
        if line.startswith("diff --git"):
            skip = any(p in line.lower() for p in SKIP_PATTERNS)
        if not skip:
            filtered_lines.append(line)

    filtered = "\n".join(filtered_lines)
    if len(filtered) > MAX_DIFF_CHARS:
        filtered = filtered[:MAX_DIFF_CHARS] + "\n\n[diff 过长，已截断]"
    return filtered


def get_pr_comments():
    """拉取 PR 所有评论，返回 (ai_reviews, all_comments_text)。
    ai_reviews: 按时间排序的 AI review 列表（含 body 和 created_at）
    all_comments_text: 供构建上下文用的完整对话文本
    """
    url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
    resp = requests.get(url, headers=GITHUB_HEADERS, params={"per_page": 100}, timeout=30)
    resp.raise_for_status()
    comments = resp.json()

    ai_reviews = [c for c in comments if c["body"].startswith(AI_REVIEW_MARKER)]

    # 构建对话摘要：每条评论标注作者类型和时间
    lines = []
    for c in comments:
        is_ai = c["body"].startswith(AI_REVIEW_MARKER)
        author = "AI Reviewer" if is_ai else f"作者（{c['user']['login']}）"
        lines.append(f"[{c['created_at']}] {author}：\n{c['body']}\n")
    all_comments_text = "\n---\n".join(lines)

    return ai_reviews, all_comments_text


def call_claude(diff, history_text=None):
    """
    首次 review：单轮，全量 diff，使用 SYSTEM_PROMPT。
    后续 review：多轮，携带历史对话 + 增量 diff，使用 INCREMENTAL_SYSTEM_PROMPT。
    """
    if not history_text:
        system = SYSTEM_PROMPT
        messages = [
            {"role": "user", "content": f"请 review 以下代码变更：\n\n```diff\n{diff}\n```"}
        ]
    else:
        system = INCREMENTAL_SYSTEM_PROMPT
        messages = [
            {
                "role": "user",
                "content": (
                    "以下是此 PR 目前的完整评论历史，包含之前的 AI review 和作者的回复：\n\n"
                    f"{history_text}\n\n"
                    "请记住以上上下文。"
                ),
            },
            {
                "role": "assistant",
                "content": "已了解 PR 的历史评论和作者的回复，我会在本次 review 中参考这些上下文。",
            },
            {
                "role": "user",
                "content": (
                    "作者在此之后推送了新的 commit，增量 diff 如下：\n\n"
                    f"```diff\n{diff}\n```\n\n"
                    "请基于以上历史上下文进行增量 review。"
                ),
            },
        ]

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1024,
            "system": system,
            "messages": messages,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"]


def post_comment(body):
    url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
    resp = requests.post(
        url,
        headers=GITHUB_HEADERS,
        json={"body": f"{AI_REVIEW_MARKER}\n\n{body}"},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Comment posted: {resp.json()['html_url']}")


if __name__ == "__main__":
    print("Getting diff...")
    diff = get_diff()

    if not diff.strip():
        print("No diff found, skipping.")
        exit(0)

    print(f"Diff length: {len(diff)} chars")

    print("Fetching PR comments...")
    ai_reviews, history_text = get_pr_comments()

    if ai_reviews:
        print(f"Found {len(ai_reviews)} previous AI review(s), using incremental mode.")
        review = call_claude(diff, history_text=history_text)
    else:
        print("No previous AI review found, using full review mode.")
        review = call_claude(diff)

    print("Posting comment...")
    post_comment(review)
    print("Done.")