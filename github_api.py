#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub API：获取 PR 文件与统计"""

import requests

class GitHubAPI:
    def __init__(self, timeout=10, token=None):
        self.timeout = timeout
        self.base_url = "https://api.github.com"
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "GitHub-Feishu-Bot/1.0"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self._token = token

    def _get(self, url):
        r = requests.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 401 and self._token:
            h = self.headers.copy()
            h["Authorization"] = f"token {self._token}"
            r = requests.get(url, headers=h, timeout=self.timeout)
        return r

    def get_pr_files(self, repo_name, pr_number):
        url = f"{self.base_url}/repos/{repo_name}/pulls/{pr_number}/files"
        r = self._get(url)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            raise Exception("401 Unauthorized")
        if r.status_code == 403:
            raise Exception("403 Forbidden")
        if r.status_code == 404:
            raise Exception("404 Not Found")
        raise Exception(f"{r.status_code}")

    def format_git_file_stats(self, repo_name, pr_number):
        files = self.get_pr_files(repo_name, pr_number)
        if not files:
            return "No files changed"
        max_depth = max(len(f.get('filename', '').split('/')) for f in files)
        depth = max_depth
        for d in range(2, max_depth + 1):
            if len(self._group(files, d)) > 1:
                depth = d
                break
        stats = self._group(files, depth)
        max_len = max(len(k) for k in stats) if stats else 0
        lines = []
        for k, v in stats.items():
            a, d, c = v['total_additions'], v['total_deletions'], v['file_count']
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
            path = f.get('filename', '').split('/')
            key = '/'.join(path[:depth]) if len(path) >= depth else '/'.join(path) or "root"
            if key not in out:
                out[key] = {'total_additions': 0, 'total_deletions': 0, 'file_count': 0}
            out[key]['total_additions'] += f.get('additions', 0)
            out[key]['total_deletions'] += f.get('deletions', 0)
            out[key]['file_count'] += 1
        return out
