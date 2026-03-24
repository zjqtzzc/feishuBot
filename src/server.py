#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 服务：GitHub Webhook → handlers"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from src.config import load_config, project_root
from src.event_store import EVENT_STORE_FILENAME
from src.feishu_credential import FEISHU_TOKEN_FILENAME
from src.github_api import GitHubAPI
from src.handlers import handle

MAX_BODY = 10 * 1024 * 1024
REQUEST_TIMEOUT = 30


def _setup():
    root = project_root()
    cfg = load_config()
    token_file = os.path.join(root, FEISHU_TOKEN_FILENAME)
    store_path = os.path.join(root, EVENT_STORE_FILENAME)
    gh = GitHubAPI(token=cfg.github_token)
    return cfg, token_file, store_path, gh


class Handler(BaseHTTPRequestHandler):
    cfg, token_file, store_path, github_api = _setup()

    def do_POST(self):
        if urlparse(self.path).path not in ("/", "/webhook"):
            self._json(404, {"error": "Not Found"})
            return
        n = int(self.headers.get("Content-Length", 0))
        if n < 0 or n > MAX_BODY:
            self._json(400, {"error": "Invalid Content-Length"})
            return
        self.connection.settimeout(REQUEST_TIMEOUT)
        raw = self.rfile.read(n) if n else b""
        event_type = self.headers.get("X-GitHub-Event", "")
        print(f"do_POST begin path={self.path} event={event_type} len={n}", flush=True)

        data = None
        if event_type in ("pull_request", "pull_request_review", "issue_comment"):
            try:
                data = json.loads(raw.decode("utf-8")) if raw else None
            except json.JSONDecodeError:
                self._json(400, {"error": "Invalid JSON"})
                return

        body, code = handle(
            raw,
            self.headers.get("X-Hub-Signature-256", ""),
            event_type,
            data,
            self.cfg,
            self.token_file,
            self.store_path,
            self.github_api,
        )
        status = body.get("status") or body.get("error", "")
        if status == "ignored":
            reason = body.get("action") or body.get("event") or body.get("reason") or ""
            print(f"Webhook {event_type} -> {code} ignored ({reason})", flush=True)
        else:
            print(f"Webhook {event_type} -> {code} {status}", flush=True)
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


class QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc_type, exc_value, _ = sys.exc_info()
        if exc_type in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            print(f"Client closed: {client_address[0]}:{client_address[1]}", flush=True)
            return
        super().handle_error(request, client_address)


def main():
    port = Handler.cfg.github_webhook_port
    try:
        QuietHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except OSError as e:
        if getattr(e, "errno", None) == 98:
            print(f"Bind failed: port={port} errno=98 Address already in use", flush=True)
        raise
