#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往指定群发送几种状态的示例卡片，用来检查卡片排版。

在安装目录运行（读取 data/config.json 里的飞书应用凭据）：
    cd output/app && BOT_DATA_DIR=../data ../venv/bin/python scripts/preview_card.py <chat_id> [示例序号 ...]
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.feishu_api import send_interactive_card
from src.feishu_card import build_status_card
from src.feishu_credential import get_tenant_access_token

REPO = "TechCrafters-5/popstar-dev"
PR = {
    "number": 1260,
    "title": "Feat(ethercat)：ENI 全离线时 is_igh_ready() 跳过真实总线探测",
    "html_url": "https://github.com/TechCrafters-5/popstar-dev/pull/1260",
    "state": "open",
    "draft": False,
    "merged": False,
    "user": {"login": "zhenyonghit"},
    "head": {"ref": "feat/igh-ready-skip-offline-eni"},
    "base": {"ref": "develop"},
    "changed_files": 3,
    "additions": 52,
    "deletions": 1,
    "commits": 1,
    "requested_reviewers": [{"login": "steve-zhan"}],
    "requested_teams": [],
}
AI_OK = {"user": {"login": "github-actions[bot]", "type": "Bot"},
         "body": "## 总结\n**改动**：……\n**结论**：可以接受，逻辑正确且测试覆盖合理。"}
AI_BAD = {"user": {"login": "github-actions[bot]", "type": "Bot"},
          "body": "## 总结\n**改动**：……\n**结论**：不可接受，存在空指针风险。"}
HUMAN = {"user": {"login": "zjqtzzc", "type": "User"}, "body": "LGTM"}
ACTIVITY = {"text": "**zjqtzzc** commented", "at": time.time()}
_J = "popstar-miniapp-api/src/main/java/com/tc/popstar/"
FILES = [{"filename": n, "additions": a, "deletions": d} for n, a, d in [
    (_J + "controller/QueueController.java", 120, 0), (_J + "controller/StoreController.java", 40, 1),
    (_J + "service/QueueService.java", 60, 1), (_J + "service/impl/QueueServiceImpl.java", 30, 0),
    (_J + "config/NacosConfig.java", 15, 0), (_J + "config/ConfigService.java", 8, 0),
    (_J + "dto/QueueDTO.java", 2, 0), (_J + "vo/QueueVO.java", 1, 0),
    ("popstar-miniapp-provider/Dockerfile", 0, 11), ("popstar-miniapp-provider/src/main/java/com/tc/App.java", 86, 7),
]]

_AI_JOB = {"id": 1, "name": "ai-review", "status": "completed", "conclusion": "success"}
CI_RUNNING = [_AI_JOB, {"id": 2, "name": "build-test", "status": "in_progress", "conclusion": None,
                        "started_at": "2026-10-28T10:12:00Z"}]
CI_QUEUED = [{"id": 2, "name": "build-test", "status": "queued", "conclusion": None, "started_at": "2026-10-28T10:05:00Z"}]
CI_OK = [_AI_JOB, {"id": 2, "name": "build-test", "status": "completed", "conclusion": "success",
                   "started_at": "2026-10-28T10:12:00Z", "completed_at": "2026-10-28T10:35:00Z"}]
CI_FAIL = [{"id": 2, "name": "build-test", "status": "completed", "conclusion": "failure",
            "started_at": "2026-10-28T10:12:00Z", "completed_at": "2026-10-28T10:30:00Z",
            "html_url": "https://github.com/TechCrafters-5/popstar-dev/actions/runs/1/job/2"}]

# (名称, PR, reviews, 评论, 最近动态, 读取失败, 改动文件, CI jobs, CI 失败步骤)
SAMPLES = [
    ("进行中：待审 + AI 通过 + CI 运行中", PR, [], [AI_OK, HUMAN], ACTIVITY, {}, FILES, CI_RUNNING, None),
    ("进行中：通过 + 要求修改 + AI 不通过（第 2 轮）",
     {**PR, "requested_reviewers": []},
     [{"user": {"login": "zhanbo86"}, "state": "APPROVED"}, {"user": {"login": "steve-zhan"}, "state": "CHANGES_REQUESTED"}],
     [AI_OK, AI_BAD], {"text": "**zhanbo86** approved", "at": time.time()}, {}, FILES[:3], CI_FAIL, "Run tests (ci_test.sh)"),
    ("进行中：评论、改动文件、CI 无权限读取", PR, [], None, ACTIVITY, {"comments": 403, "files": 403, "ci": 403},
     None, None, None),
    ("Draft + CI 排队中", {**PR, "draft": True}, [], [], {"text": "**zhenyonghit** converted to draft", "at": time.time()},
     {}, [{"filename": "src/ethercat/igh_ready.cpp", "additions": 52, "deletions": 1}], CI_QUEUED, None),
    ("已合并", {**PR, "state": "closed", "merged": True, "merged_by": {"login": "zhanbo86"}}, [], [AI_OK, AI_BAD], None, {},
     None, None, None),
    ("进行中：CI 通过", PR, [{"user": {"login": "zhanbo86"}, "state": "APPROVED"}], [AI_OK], ACTIVITY, {}, FILES, CI_OK, None),
]

def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    chat_id = sys.argv[1]
    cfg = load_config()
    token = get_tenant_access_token(cfg.app_id, cfg.app_secret)
    if not token:
        sys.exit("获取飞书 token 失败，检查 config.json 的 app_id / app_secret")

    only = sys.argv[2:]  # 可选：只发指定序号的示例，如 0 4
    for i, (name, pr, reviews, comments, activity, errors, files, ci_runs, ci_step) in enumerate(SAMPLES):
        if only and str(i) not in only:
            continue
        card = build_status_card(pr, reviews, comments, activity, REPO, {}, errors, files, ci_runs, ci_step)
        print(f"{name}: {'OK' if send_interactive_card(token, chat_id, card) else '发送失败'}")


if __name__ == "__main__":
    main()
