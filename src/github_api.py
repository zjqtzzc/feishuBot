#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub API：PR 文件统计、compare 提交列表"""

import logging
import time

import requests
from requests.exceptions import ConnectionError, Timeout

log = logging.getLogger(__name__)


class GitHubAPITimeout(Exception):
    pass


class GitHubAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GitHubAPI:
    def __init__(self, timeout=5, token=None):
        self.timeout = timeout
        self.base_url = "https://api.github.com"
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "GitHub-Feishu-Bot/1.0"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self._token = token

    def _get(self, url):
        t0 = time.monotonic()
        try:
            r = requests.get(url, headers=self.headers, timeout=self.timeout)
        except (Timeout, ConnectionError) as e:
            elapsed = time.monotonic() - t0
            log.warning("GitHubAPI GET failed url=%s %.3fs %s", url, elapsed, type(e).__name__)
            raise GitHubAPITimeout(str(e)) from e
        if r.status_code == 401 and self._token:
            h = self.headers.copy()
            h["Authorization"] = f"token {self._token}"
            try:
                r = requests.get(url, headers=h, timeout=self.timeout)
            except (Timeout, ConnectionError) as e:
                elapsed = time.monotonic() - t0
                log.warning("GitHubAPI GET failed url=%s %.3fs %s", url, elapsed, type(e).__name__)
                raise GitHubAPITimeout(str(e)) from e
        elapsed = time.monotonic() - t0
        log.debug("GitHubAPI GET url=%s status=%s %.3fs", url, r.status_code, elapsed)
        return r

    def get_pr_files(self, repo_name, pr_number):
        url = f"{self.base_url}/repos/{repo_name}/pulls/{pr_number}/files"
        r = self._get(url)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            raise GitHubAPIError("401 Unauthorized", status_code=401)
        if r.status_code == 403:
            raise GitHubAPIError("403 Forbidden", status_code=403)
        if r.status_code == 404:
            raise GitHubAPIError("404 Not Found", status_code=404)
        raise GitHubAPIError(str(r.status_code), status_code=r.status_code)

    def format_git_file_stats(self, repo_name, pr_number):
        files = self.get_pr_files(repo_name, pr_number)
        if not files:
            return "No files changed"
        max_depth = max(len(f.get("filename", "").split("/")) for f in files)
        depth = max_depth
        for d in range(2, max_depth + 1):
            if len(self._group(files, d)) > 1:
                depth = d
                break
        stats = self._group(files, depth)
        max_len = max(len(k) for k in stats) if stats else 0
        lines = []
        for k, v in stats.items():
            a, d, c = v["total_additions"], v["total_deletions"], v["file_count"]
            ch = []
            if a > 0:
                ch.append(f"<font color='green'>+{a}</font>")
            if d > 0:
                ch.append(f"<font color='red'>-{d}</font>")
            lines.append(f" {k:<{max_len}} | {a+d:>3} {' '.join(ch) or '0'} ({c} files)")
        return "\n".join(lines)

    def _group(self, files, depth):
        out = {}
        for f in files:
            path = f.get("filename", "").split("/")
            key = "/".join(path[:depth]) if len(path) >= depth else "/".join(path) or "root"
            if key not in out:
                out[key] = {"total_additions": 0, "total_deletions": 0, "file_count": 0}
            out[key]["total_additions"] += f.get("additions", 0)
            out[key]["total_deletions"] += f.get("deletions", 0)
            out[key]["file_count"] += 1
        return out

    def get_commit_title_line(self, repo_name: str, sha: str) -> str:
        """GET /commits/{sha}，返回 message 首行（subject）。"""
        if not sha or len(sha) < 7:
            return ""
        url = f"{self.base_url}/repos/{repo_name}/commits/{sha}"
        r = self._get(url)
        if r.status_code != 200:
            return ""
        j = r.json()
        msg = (j.get("commit") or {}).get("message") or ""
        return msg.split("\n", 1)[0].strip()[:200]

    def get_commits_between(self, repo_name: str, base_sha: str, head_sha: str) -> tuple[int, str, list[str]]:
        """compare base...head，返回 (total_commits, head 短 SHA, 每条 commit 的 message 首行)。"""
        if not head_sha:
            return 0, "", []

        short = head_sha[:7]
        if not base_sha or base_sha.startswith("0" * 7):
            title = self.get_commit_title_line(repo_name, head_sha)
            return 1, short, [title] if title else []

        url = f"{self.base_url}/repos/{repo_name}/compare/{base_sha}...{head_sha}"
        r = self._get(url)
        if r.status_code != 200:
            title = self.get_commit_title_line(repo_name, head_sha)
            return 1, short, [title] if title else []

        j = r.json()
        total = int(j.get("total_commits", 0))
        commits = j.get("commits") or []
        msgs = []
        for c in commits:
            msg = (c.get("commit") or {}).get("message") or ""
            first = msg.split("\n", 1)[0].strip()[:120]
            if first:
                msgs.append(first)
        if not msgs and head_sha:
            title = self.get_commit_title_line(repo_name, head_sha)
            if title:
                msgs = [title]
        return total, short, msgs
