#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub PR 通知到飞书：接收 webhook，发送/更新消息卡片"""

import json
import hmac
import hashlib
import os

import requests

from feishu_card import build_pr_card
from feishu_credential import (
    FEISHU_TOKEN_FILENAME,
    PR_MESSAGE_MAP_FILENAME,
    PrMessageMapping,
    get_tenant_access_token,
)
from github_api import GitHubAPI
from config import load_config
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

cfg = load_config()
WEBHOOK_SECRET = ""
github_api = GitHubAPI(token=cfg.github_token)
script_dir = os.path.dirname(os.path.abspath(__file__))
token_file = os.path.join(script_dir, FEISHU_TOKEN_FILENAME)
map_file = os.path.join(script_dir, PR_MESSAGE_MAP_FILENAME)
pr_mapping = PrMessageMapping(map_file)


def verify_signature(payload: bytes, sig: str) -> bool:
    if not WEBHOOK_SECRET:
        return True
    expect = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expect)


def _card_type(data: dict) -> str:
    action = data.get("action", "")
    pr = data.get("pull_request", {})
    if action == "closed":
        return "merged" if pr.get("merged") else "closed"
    if action == "reopened":
        return "open"
    return "open"


def send_card(token: str, event_data: dict, card_type: str) -> str | None:
    payload = build_pr_card(event_data, card_type, github_api)
    card = payload["card"]
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    params = {"receive_id_type": "chat_id"}
    body = {"receive_id": cfg.chat_id, "msg_type": "interactive", "content": json.dumps(card)}
    r = requests.post(url, headers=headers, params=params, json=body, timeout=10)
    data = r.json()
    if data.get("code") != 0:
        return None
    return data.get("data", {}).get("message_id")


def update_card(token: str, message_id: str, event_data: dict, card_type: str) -> bool:
    payload = build_pr_card(event_data, card_type, github_api)
    card = payload["card"]
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    r = requests.patch(url, headers=headers, json={"content": json.dumps(card)}, timeout=10)
    return r.json().get("code") == 0


def handle(payload: bytes, sig: str, event_type: str, data: dict | None) -> tuple[dict, int]:
    if not verify_signature(payload, sig):
        return {"error": "Invalid signature"}, 401
    if not data:
        return {"error": "Empty payload"}, 400
    if event_type != "pull_request":
        return {"status": "ignored"}, 200
    action = data.get("action", "")
    if action not in ("opened", "synchronize", "reopened", "edited", "closed"):
        return {"status": "ignored"}, 200

    pr = data.get("pull_request", {})
    repo = data.get("repository", {})
    repo_name = repo.get("full_name", "")
    pr_number = pr.get("number", "")
    if not repo_name or not pr_number:
        return {"error": "Missing repo/pr"}, 400

    token = get_tenant_access_token(cfg.app_id, cfg.app_secret, token_file)
    if not token:
        return {"error": "Feishu token failed"}, 500

    card_type = _card_type(data)
    print(f"PR [{card_type}] {pr.get('title', '')}")
    message_id = pr_mapping.get(repo_name, pr_number)

    if message_id:
        ok = update_card(token, message_id, data, card_type)
    else:
        message_id = send_card(token, data, card_type)
        if message_id:
            pr_mapping.set(repo_name, pr_number, message_id)
        ok = bool(message_id)

    return ({"status": "success"}, 200) if ok else ({"error": "Feishu send/update failed"}, 500)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if urlparse(self.path).path not in ("/", "/webhook"):
            self._json(404, {"error": "Not Found"})
            return
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else None
        except json.JSONDecodeError:
            data = None
        body, code = handle(
            raw,
            self.headers.get("X-Hub-Signature-256", ""),
            self.headers.get("X-GitHub-Event", ""),
            data,
        )
        self._json(code, body)

    def _json(self, status: int, body: dict):
        b = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(b))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", cfg.github_webhook_port), Handler).serve_forever()
