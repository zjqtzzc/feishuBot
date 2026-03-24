# -*- coding: utf-8 -*-
"""飞书群消息：发送与更新交互卡片"""

import json
import logging
import time

import requests

FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
log = logging.getLogger(__name__)


def send_interactive_card(
    token: str, chat_id: str, card: dict, timeout: int = 10, ctx: str = ""
) -> str | None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    params = {"receive_id_type": "chat_id"}
    body = {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card)}
    t0 = time.monotonic()
    r = requests.post(FEISHU_MSG_URL, headers=headers, params=params, json=body, timeout=timeout)
    elapsed = time.monotonic() - t0
    data = r.json()
    p = f"{ctx} " if ctx else ""
    log.info("%sFeishu send_card http=%s code=%s %.3fs", p, r.status_code, data.get("code"), elapsed)
    if data.get("code") != 0:
        return None
    return data.get("data", {}).get("message_id")


def patch_interactive_card(token: str, message_id: str, card: dict, timeout: int = 10, ctx: str = "") -> bool:
    url = f"{FEISHU_MSG_URL}/{message_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    t0 = time.monotonic()
    r = requests.patch(url, headers=headers, json={"content": json.dumps(card)}, timeout=timeout)
    elapsed = time.monotonic() - t0
    data = r.json()
    p = f"{ctx} " if ctx else ""
    log.info("%sFeishu patch_card http=%s code=%s %.3fs", p, r.status_code, data.get("code"), elapsed)
    return data.get("code") == 0
