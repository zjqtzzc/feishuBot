# -*- coding: utf-8 -*-
"""时间线事件 type 字段，与飞书卡片渲染一致"""

from __future__ import annotations

from enum import Enum


class TimelineEventType(str, Enum):
    PR_OPEN = "pr_open"
    REVIEW_REQUESTED = "review_requested"
    PR_READY = "pr_ready"
    PR_PUSH = "pr_push"
    PR_REOPEN = "pr_reopen"
    PR_CLOSE = "pr_close"
    PR_MERGE = "pr_merge"
    AI_REVIEW = "ai_review"
    PR_COMMENT = "pr_comment"
    HUMAN_REVIEW = "human_review"
