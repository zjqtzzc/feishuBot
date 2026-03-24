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

SYSTEM_PROMPT = """你是一个持续跟进 PR 的专业代码 reviewer，使用中文。

重点关注：
- 潜在的 bug 或逻辑错误
- 安全风险（SQL 注入、未校验输入等）
- 明显的性能问题
- 代码可读性和命名规范

请用以下 Markdown 格式输出：

## AI Code Review 总结
（1-2 句整体评价）

## 需要关注的问题
（如果有问题，列出具体行号和说明；没有则写"无明显问题"）

## 建议改进
（可选的优化建议，非强制）

## 最终意见
（根据以上分析，给出能否接受此次 PR 的意见）

保持简洁，不要重复 diff 内容本身。"""


def get_diff():
    # 用 merge-base 找到 PR 分支真正的分叉点，避免把目标分支上其他 PR 的改动也算进来
    merge_base = subprocess.run(
        ["git", "merge-base", BASE_SHA, HEAD_SHA],
        capture_output=True, text=True
    ).stdout.strip()

    result = subprocess.run(
        ["git", "diff", merge_base, HEAD_SHA],
        capture_output=True, text=True
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
    首次 review：单轮，全量 diff。
    后续 review：多轮，携带历史对话 + 增量 diff。
    """
    if not history_text:
        # 首次：无历史
        messages = [
            {"role": "user", "content": f"请 review 以下代码变更：\n\n```diff\n{diff}\n```"}
        ]
    else:
        # 后续：将历史对话作为上下文，再给出增量 diff
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
                    "请基于以上历史上下文进行 review：\n"
                    "- 之前指出的问题是否已修复？\n"
                    "- 新代码是否引入了新问题？\n"
                    "- 无需重复之前已解决的内容。"
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
            "system": SYSTEM_PROMPT,
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