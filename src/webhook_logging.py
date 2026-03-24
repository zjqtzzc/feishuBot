# -*- coding: utf-8 -*-
"""Webhook 与 systemd 日志：统一格式与 [repo#pr] 上下文"""

from __future__ import annotations

import logging
import sys
from typing import Any


def setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def ctx_tag(event_type: str, data: dict[str, Any] | None) -> tuple[str, str]:
    """返回 (「owner/repo#n」, GitHub action)。"""
    if not data:
        return "?", ""
    repo = (data.get("repository") or {}).get("full_name") or ""
    action = data.get("action") or ""
    if event_type == "issue_comment":
        issue = data.get("issue") or {}
        n = issue.get("number")
        if repo and n:
            return f"{repo}#{n}", action
    if event_type in ("pull_request", "pull_request_review"):
        pr = data.get("pull_request") or {}
        n = pr.get("number")
        if repo and n:
            return f"{repo}#{n}", action
    return (f"{repo}?" if repo else "?"), action


def strip_log_fields(body: dict[str, Any]) -> dict[str, Any]:
    """HTTP 响应里不返回仅供日志的字段。"""
    return {k: v for k, v in body.items() if k != "detail"}
