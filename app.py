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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('github-feishu-bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 配置类
class Config:
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.config = self.load_config()
        
        # 服务配置
        self.HOST = self.config.get('host', '0.0.0.0')
        self.PORT = self.config.get('port', 8080)
        self.DEBUG = self.config.get('debug', False)
        
        # 飞书配置
        self.FEISHU_WEBHOOK_URL = self.config.get('feishu_webhook_url', '')
        
        # GitHub配置
        self.GITHUB_WEBHOOK_SECRET = self.config.get('github_webhook_secret', '')
        
        # 日志配置
        self.LOG_LEVEL = self.config.get('log_level', 'INFO')
        self.LOG_FILE = self.config.get('log_file', 'github-feishu-bot.log')
    
    def load_config(self):
        """加载配置文件"""
        # 首先尝试从当前目录加载
        config_paths = [
            self.config_file,
            os.path.join(os.path.dirname(__file__), self.config_file),
            '/opt/github-feishu-bot/config.json',
            os.path.expanduser('~/.github-feishu-bot/config.json')
        ]
        
        for config_path in config_paths:
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception as e:
                    print(f"警告: 无法读取配置文件 {config_path}: {e}")
                    continue
        
        # 如果没有找到配置文件，返回默认配置
        print("警告: 未找到配置文件，使用默认配置")
        return self.get_default_config()
    
    def get_default_config(self):
        """获取默认配置"""
        return {
            'host': '0.0.0.0',
            'port': 8080,
            'debug': False,
            'feishu_webhook_url': '',
            'github_webhook_secret': '',
            'log_level': 'INFO',
            'log_file': 'github-feishu-bot.log'
        }
    
    def validate(self) -> bool:
        """验证配置是否完整"""
        if not self.FEISHU_WEBHOOK_URL:
            return False
        return True

# 获取配置
config = Config()

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

def format_test_message():
    """格式化测试消息"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    message = {
        "msg_type": "interactive",
        "card": {
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": f"**🧪 服务测试消息**\n\n**服务状态**: ✅ 运行正常\n**启动时间**: {current_time}\n**服务端口**: {config.PORT}\n\n这是一条测试消息，用于验证飞书机器人连接是否正常。",
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "content": "健康检查",
                                "tag": "plain_text"
                            },
                            "type": "primary",
                            "url": f"http://{config.HOST}:{config.PORT}/health"
                        }
                    ]
                }
            ],
            "header": {
                "template": "green",
                "title": {
                    "content": "GitHub PR Bot 测试",
                    "tag": "plain_text"
                }
            }
        }
    }
    
    return message

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
    
    # 获取需要review的人
    requested_reviewers = pr.get('requested_reviewers', [])
    reviewer_names = [reviewer.get('login', '') for reviewer in requested_reviewers if reviewer.get('login')]
    
    # 构建内容
    content_lines = [
        f"**{pr_title}**",
        "",
        f"**提交人**: {sender_name}",
    ]
    
    if reviewer_names:
        content_lines.append(f"**需要Review**: {', '.join(reviewer_names)}")
    else:
        content_lines.append("**需要Review**: 暂无指定")
    
    # 构建飞书消息卡片
    message = {
        "msg_type": "interactive",
        "card": {
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": "\n".join(content_lines),
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
                    "content": f"{repo_name}: New Pull Request",
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
            # 检查PR动作类型，只处理新增的PR
            action = event_data.get('action', '')
            if action == 'opened':
                logger.info(f"处理新增PR事件: {action}")
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
                logger.info(f"忽略PR动作类型: {action}")
                return jsonify({'status': 'ignored', 'reason': f'Action {action} not handled'}), 200
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

@app.route('/test', methods=['POST'])
def send_test_message():
    """发送测试消息到飞书"""
    try:
        message = format_test_message()
        if send_to_feishu(message):
            logger.info("测试消息发送成功")
            return jsonify({'status': 'success', 'message': '测试消息发送成功'}), 200
        else:
            logger.error("测试消息发送失败")
            return jsonify({'status': 'error', 'message': '测试消息发送失败'}), 500
    except Exception as e:
        logger.error(f"发送测试消息时发生错误: {e}")
        return jsonify({'status': 'error', 'message': f'发送测试消息时发生错误: {e}'}), 500

@app.route('/', methods=['GET', 'POST'])
def index():
    """根路径"""
    if request.method == 'POST':
        # 检查是否是GitHub webhook请求
        github_event = request.headers.get('X-GitHub-Event', '')
        if github_event:
            logger.info(f"收到GitHub webhook请求，事件类型: {github_event}")
            # 重定向到webhook处理逻辑
            return github_webhook()
        else:
            logger.info(f"收到根路径POST请求，来源IP: {request.remote_addr}")
            logger.info(f"请求头: {dict(request.headers)}")
            if request.is_json:
                logger.info(f"请求数据: {request.get_json()}")
            else:
                logger.info(f"请求数据: {request.get_data()}")
    
    return jsonify({
        'service': 'GitHub PR to Feishu Bot',
        'version': '1.0.0',
        'endpoints': {
            'webhook': '/webhook',
            'health': '/health',
            'test': '/test'
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
