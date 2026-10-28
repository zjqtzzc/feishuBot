#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub API：读取 PR 当前状态（PR、reviews、评论）"""

import logging
import time

import requests
from requests.exceptions import RequestException

log = logging.getLogger(__name__)

# 分页上限，防止异常 PR 拉取过多
MAX_PAGES = 10


class GitHubAPIError(Exception):
    pass


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
            raise GitHubAPIError(f"GET {url} HTTP {r.status_code}")
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
