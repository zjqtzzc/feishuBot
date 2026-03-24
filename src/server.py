#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 服务：GitHub Webhook → handlers"""

import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from src.config import load_config, project_root
from src.event_store import EVENT_STORE_FILENAME
from src.feishu_credential import FEISHU_TOKEN_FILENAME
from src.github_api import GitHubAPI
from src.handlers import handle
from src.webhook_logging import ctx_tag, setup_logging, strip_log_fields

log = logging.getLogger(__name__)

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
        delivery = (self.headers.get("X-GitHub-Delivery") or "")[:8]

        data = None
        if event_type in ("pull_request", "pull_request_review", "issue_comment"):
            try:
                data = json.loads(raw.decode("utf-8")) if raw else None
            except json.JSONDecodeError:
                self._json(400, {"error": "Invalid JSON"})
                return

        tag, gh_action = ctx_tag(event_type, data)
        t0 = time.monotonic()
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
        elapsed = time.monotonic() - t0
        status = body.get("status") or body.get("error", "")
        detail = body.get("detail", "")
        if detail:
            tail = detail
        elif status == "ignored":
            tail = body.get("reason") or body.get("action") or body.get("event") or "-"
        else:
            tail = "-"
        log.info(
            "[%s] %s action=%s -> HTTP %s %s %s %.3fs delivery=%s",
            tag,
            event_type,
            gh_action or "-",
            code,
            status,
            tail,
            elapsed,
            delivery or "-",
        )
        self._json(code, strip_log_fields(body))

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
            log.debug("client closed %s:%s", client_address[0], client_address[1])
            return
        super().handle_error(request, client_address)


def main():
    setup_logging()
    port = Handler.cfg.github_webhook_port
    try:
        QuietHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except OSError as e:
        if getattr(e, "errno", None) == 98:
            log.error("bind failed port=%s address already in use", port)
        raise
