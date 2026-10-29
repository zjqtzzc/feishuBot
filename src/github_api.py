#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub API：读取 PR 当前状态（PR、reviews、评论、改动文件、CI）"""

import logging
import time

import requests
from requests.exceptions import RequestException

log = logging.getLogger(__name__)

# 分页上限，防止异常 PR 拉取过多
MAX_PAGES = 10


class GitHubAPIError(Exception):
    def __init__(self, message: str, status: int | None = None, rate_limited: bool = False):
        super().__init__(message)
        self.status = status
        self.rate_limited = rate_limited

    @property
    def permanent(self) -> bool:
        """token 无效或无权限：重试也没用。网络错误、5xx、限流不算。"""
        return self.status in (401, 403, 404) and not self.rate_limited


class GitHubAPI:
    def __init__(self, timeout=5, token=None):
        self.timeout = timeout
        self.base_url = "https://api.github.com"
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "GitHub-Feishu-Bot/1.0"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _get(self, url, params=None):
        t0 = time.monotonic()
        try:
            r = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
        except RequestException as e:
            raise GitHubAPIError(f"GET {url} {type(e).__name__}") from e
        log.debug("GitHubAPI GET url=%s status=%s %.3fs", url, r.status_code, time.monotonic() - t0)
        if r.status_code != 200:
            rate_limited = r.headers.get("x-ratelimit-remaining") == "0" or r.status_code == 429
            try:
                reason = r.json().get("message", "")
            except ValueError:
                reason = ""
            raise GitHubAPIError(f"GET {url} HTTP {r.status_code} {reason}".rstrip(), r.status_code, rate_limited)
        return r

    def _get_all(self, url):
        out = []
        params = {"per_page": 100}
        for _ in range(MAX_PAGES):
            r = self._get(url, params)
            out.extend(r.json())
            url = r.links.get("next", {}).get("url")
            if not url:
                break
            params = None
        return out

    def get_pull(self, repo_name, pr_number):
        return self._get(f"{self.base_url}/repos/{repo_name}/pulls/{pr_number}").json()

    def list_reviews(self, repo_name, pr_number):
        return self._get_all(f"{self.base_url}/repos/{repo_name}/pulls/{pr_number}/reviews")

    def list_issue_comments(self, repo_name, pr_number):
        return self._get_all(f"{self.base_url}/repos/{repo_name}/issues/{pr_number}/comments")

    def list_files(self, repo_name, pr_number):
        return self._get_all(f"{self.base_url}/repos/{repo_name}/pulls/{pr_number}/files")

    def list_ci_jobs(self, repo_name, sha, exclude=()):
        """commit 触发的所有 Actions job（含 steps）。

        用 Actions 接口而不是 Checks 接口：fine-grained token 没有 Checks 权限。
        exclude：workflow 名称或文件路径（小写）包含其中任一项的 run 跳过，不查它的 job。
        """
        params = {"head_sha": sha, "per_page": 100}
        runs = self._get(f"{self.base_url}/repos/{repo_name}/actions/runs", params).json().get("workflow_runs") or []
        jobs = []
        for run in runs:
            label = f"{run.get('name', '')} {run.get('path', '')}".lower()
            if any(x in label for x in exclude):
                continue
            url = f"{self.base_url}/repos/{repo_name}/actions/runs/{run['id']}/jobs"
            jobs.extend(self._get(url, {"per_page": 100}).json().get("jobs") or [])
        return jobs

    def find_open_pr(self, repo_name, branch):
        """分支上打开的 PR 号，没有则返回 None。"""
        owner = repo_name.split("/")[0]
        params = {"head": f"{owner}:{branch}", "state": "open"}
        pulls = self._get(f"{self.base_url}/repos/{repo_name}/pulls", params).json()
        return pulls[0]["number"] if pulls else None
