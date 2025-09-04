#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub PR 通知到飞书机器人服务
处理GitHub webhook事件，发送PR通知到飞书群聊
"""

import os
import json
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime
import logging
from config import get_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/github-feishu-bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 获取配置
config = get_config()

def verify_github_signature(payload, signature):
    """验证GitHub webhook签名"""
    if not config.GITHUB_WEBHOOK_SECRET:
        logger.warning("GitHub webhook secret not configured, skipping signature verification")
        return True
    
    expected_signature = 'sha256=' + hmac.new(
        config.GITHUB_WEBHOOK_SECRET.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)

def format_pr_message(event_data):
    """格式化PR消息"""
    action = event_data.get('action', '')
    pr = event_data.get('pull_request', {})
    repository = event_data.get('repository', {})
    sender = event_data.get('sender', {})
    
    # 获取基本信息
    pr_title = pr.get('title', '')
    pr_url = pr.get('html_url', '')
    pr_number = pr.get('number', '')
    repo_name = repository.get('full_name', '')
    sender_name = sender.get('login', '')
    sender_avatar = sender.get('avatar_url', '')
    
    # 根据action类型设置消息
    action_messages = {
        'opened': '🆕 新的Pull Request',
        'closed': '✅ Pull Request已关闭',
        'merged': '🎉 Pull Request已合并',
        'reopened': '🔄 Pull Request重新打开',
        'review_requested': '👀 请求代码审查',
        'synchronize': '🔄 Pull Request已更新'
    }
    
    action_text = action_messages.get(action, f'📝 Pull Request {action}')
    
    # 构建飞书消息卡片
    message = {
        "msg_type": "interactive",
        "card": {
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": f"**{action_text}**\n\n**仓库**: {repo_name}\n**PR #{pr_number}**: {pr_title}\n**作者**: {sender_name}",
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "content": "查看PR",
                                "tag": "plain_text"
                            },
                            "type": "primary",
                            "url": pr_url
                        }
                    ]
                }
            ],
            "header": {
                "template": "blue",
                "title": {
                    "content": f"GitHub PR 通知",
                    "tag": "plain_text"
                }
            }
        }
    }
    
    return message

def send_to_feishu(message):
    """发送消息到飞书"""
    if not config.FEISHU_WEBHOOK_URL:
        logger.error("飞书webhook URL未配置")
        return False
    
    try:
        response = requests.post(
            config.FEISHU_WEBHOOK_URL,
            json=message,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                logger.info("消息发送到飞书成功")
                return True
            else:
                logger.error(f"飞书返回错误: {result}")
                return False
        else:
            logger.error(f"发送到飞书失败，状态码: {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"发送到飞书时发生网络错误: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def github_webhook():
    """处理GitHub webhook"""
    try:
        # 获取请求数据
        payload = request.get_data()
        signature = request.headers.get('X-Hub-Signature-256', '')
        
        # 验证签名
        if not verify_github_signature(payload, signature):
            logger.warning("GitHub webhook签名验证失败")
            return jsonify({'error': 'Invalid signature'}), 401
        
        # 解析JSON数据
        event_data = request.get_json()
        if not event_data:
            logger.warning("收到空的webhook数据")
            return jsonify({'error': 'Empty payload'}), 400
        
        # 检查事件类型
        event_type = request.headers.get('X-GitHub-Event', '')
        logger.info(f"收到GitHub事件: {event_type}")
        
        # 只处理pull_request事件
        if event_type == 'pull_request':
            # 格式化消息
            message = format_pr_message(event_data)
            
            # 发送到飞书
            if send_to_feishu(message):
                logger.info("PR通知发送成功")
                return jsonify({'status': 'success'}), 200
            else:
                logger.error("PR通知发送失败")
                return jsonify({'error': 'Failed to send to Feishu'}), 500
        else:
            logger.info(f"忽略事件类型: {event_type}")
            return jsonify({'status': 'ignored'}), 200
            
    except Exception as e:
        logger.error(f"处理webhook时发生错误: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'github-feishu-bot'
    }), 200

@app.route('/', methods=['GET'])
def index():
    """根路径"""
    return jsonify({
        'service': 'GitHub PR to Feishu Bot',
        'version': '1.0.0',
        'endpoints': {
            'webhook': '/webhook',
            'health': '/health'
        }
    }), 200

if __name__ == '__main__':
    # 检查必要的配置
    if not config.validate():
        logger.error("配置验证失败，请检查环境变量")
        exit(1)
    
    logger.info(f"启动GitHub PR通知服务，端口: {config.PORT}")
    logger.info(f"飞书webhook URL: {config.FEISHU_WEBHOOK_URL[:50]}...")
    
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
