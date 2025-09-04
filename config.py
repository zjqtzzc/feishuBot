#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub PR to Feishu Bot 配置文件
统一管理所有配置参数
"""

import os
from typing import Optional

class Config:
    """应用配置类"""
    
    # 服务配置
    HOST = '0.0.0.0'
    PORT = int(os.getenv('PORT', 8080))
    DEBUG = False
    
    # 飞书配置
    FEISHU_WEBHOOK_URL = os.getenv('FEISHU_WEBHOOK_URL', '')
    
    # GitHub配置
    GITHUB_WEBHOOK_SECRET = os.getenv('GITHUB_WEBHOOK_SECRET', '')
    
    # 日志配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = '/var/log/github-feishu-bot.log'
    
    @classmethod
    def validate(cls) -> bool:
        """验证配置是否完整"""
        if not cls.FEISHU_WEBHOOK_URL:
            return False
        return True

# 开发环境配置
class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True
    LOG_LEVEL = 'DEBUG'

# 生产环境配置
class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False
    LOG_LEVEL = 'INFO'

# 根据环境变量选择配置
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': ProductionConfig
}

def get_config() -> Config:
    """获取当前环境配置"""
    env = os.getenv('FLASK_ENV', 'default')
    return config.get(env, ProductionConfig)
