# -*- coding: utf-8 -*-
"""飞书群消息：发送与更新交互卡片"""

import json
import logging
import time

import requests
from requests.exceptions import RequestException

FEISHU_MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
log = logging.getLogger(__name__)

# 限流类错误：重发新卡片也没用，不触发「卡片失效重发」
RATE_LIMIT_CODES = frozenset({99991400, 230020})


def _call(method: str, url: str, token: str, body: dict | None, params: dict | None = None,
          timeout: int = 10, ctx: str = "", op: str = "") -> tuple[int | None, dict]:
    """返回 (code, data)；网络错误或响应不是 JSON 时 code 为 None。"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    p = f"{ctx} " if ctx else ""
    t0 = time.monotonic()
    try:
        r = requests.request(method, url, headers=headers, params=params, json=body, timeout=timeout)
        data = r.json()
    except (RequestException, ValueError) as e:
        log.warning("%sFeishu %s error %.3fs %s", p, op, time.monotonic() - t0, e)
        return None, {}
    code = data.get("code")
    log.info("%sFeishu %s http=%s code=%s %.3fs", p, op, r.status_code, code, time.monotonic() - t0)
    if code != 0:
        log.warning("%sFeishu %s msg=%s", p, op, data.get("msg"))
    return code, data


def _send(token: str, chat_id: str, msg_type: str, content: dict, ctx: str, op: str) -> str | None:
    body = {"receive_id": chat_id, "msg_type": msg_type, "content": json.dumps(content)}
    code, data = _call("POST", FEISHU_MSG_URL, token, body, {"receive_id_type": "chat_id"}, ctx=ctx, op=op)
    if code != 0:
        return None
    return (data.get("data") or {}).get("message_id")


def send_interactive_card(token: str, chat_id: str, card: dict, ctx: str = "") -> str | None:
    return _send(token, chat_id, "interactive", card, ctx, "send_card")


def send_text_message(token: str, chat_id: str, text: str, ctx: str = "") -> bool:
    return _send(token, chat_id, "text", {"text": text}, ctx, "send_text") is not None


def patch_interactive_card(token: str, message_id: str, card: dict, ctx: str = "") -> int | None:
    """返回飞书 code：0 成功，None 网络错误。"""
    code, _ = _call("PATCH", f"{FEISHU_MSG_URL}/{message_id}", token, {"content": json.dumps(card)},
                    ctx=ctx, op="patch_card")
    return code


def get_chat_member_names(token: str, chat_id: str, ctx: str = "") -> dict[str, str]:
    """群成员 open_id → 飞书名字；失败返回已取到的部分。需要应用有读取群成员的权限。"""
    url = f"https://open.feishu.cn/open-apis/im/v1/chats/{chat_id}/members"
    names: dict[str, str] = {}
    params = {"member_id_type": "open_id", "page_size": 100}
    for _ in range(20):
        code, data = _call("GET", url, token, None, params, ctx=ctx, op="chat_members")
        if code != 0:
            break
        d = data.get("data") or {}
        for m in d.get("items") or []:
            names[m.get("member_id", "")] = m.get("name", "")
        if not d.get("has_more"):
            break
        params = {**params, "page_token": d.get("page_token")}
    return names
