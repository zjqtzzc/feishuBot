#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GitHub API 模块
用于获取GitHub仓库和PR相关信息
"""

import requests
import logging

logger = logging.getLogger(__name__)

class GitHubAPI:
    """GitHub API 客户端"""
    
    def __init__(self, timeout=10, token=None):
        """
        初始化GitHub API客户端
        
        Args:
            timeout (int): 请求超时时间（秒）
            token (str): GitHub Personal Access Token，用于访问私有仓库
        """
        self.timeout = timeout
        self.base_url = "https://api.github.com"
        self.token = token
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "GitHub-Feishu-Bot/1.0"
        }
        
        # 如果有token，添加到请求头
        if self.token:
            # 支持两种Token格式：
            # 1. Fine-grained tokens - 使用 Bearer 认证
            # 2. Classic tokens - 使用 token 认证
            # 由于两种token都以 ghp_ 开头，我们默认使用 Bearer 认证
            # 如果Bearer认证失败，可以回退到token认证
            self.headers["Authorization"] = f"Bearer {self.token}"
    
    def _make_request(self, url):
        """
        发送HTTP请求，支持认证回退
        
        Args:
            url (str): 请求URL
            
        Returns:
            requests.Response: 响应对象
        """
        # 首先尝试Bearer认证
        response = requests.get(url, headers=self.headers, timeout=self.timeout)
        
        # 如果Bearer认证失败且是401错误，尝试token认证
        if response.status_code == 401 and self.token:
            logger.info("Bearer认证失败，尝试token认证")
            fallback_headers = self.headers.copy()
            fallback_headers["Authorization"] = f"token {self.token}"
            response = requests.get(url, headers=fallback_headers, timeout=self.timeout)
        
        return response

    def get_pr_files(self, repo_name, pr_number):
        """
        获取PR文件列表
        
        Args:
            repo_name (str): 仓库名称，格式为 "owner/repo"
            pr_number (int): PR编号
            
        Returns:
            list: PR文件列表，如果失败返回空列表
        """
        try:
            # 构建API URL
            api_url = f"{self.base_url}/repos/{repo_name}/pulls/{pr_number}/files"
            
            # 发送请求
            response = self._make_request(api_url)
            
            if response.status_code == 200:
                files = response.json()
                logger.info(f"成功获取PR #{pr_number} 文件列表，共 {len(files)} 个文件")
                return files
            else:
                logger.warning(f"获取PR文件列表失败，状态码: {response.status_code}, 响应: {response.text}")
                # 抛出具体的错误信息，让上层处理
                if response.status_code == 401:
                    raise Exception(f"401 Unauthorized: {response.text}")
                elif response.status_code == 403:
                    raise Exception(f"403 Forbidden: {response.text}")
                elif response.status_code == 404:
                    raise Exception(f"404 Not Found: {response.text}")
                else:
                    raise Exception(f"{response.status_code}: {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"获取PR文件列表时发生网络错误: {e}")
            raise e
        except Exception as e:
            logger.error(f"获取PR文件列表时发生未知错误: {e}")
            raise e
    
    
    def format_git_file_stats(self, repo_name, pr_number):
        """
        格式化Git风格的文件统计信息，按前2级目录分组合并
        
        Args:
            repo_name (str): 仓库名称，格式为 "owner/repo"
            pr_number (int): PR编号
            
        Returns:
            str: 格式化的文件统计信息
        """
        # 获取文件列表
        try:
            files = self.get_pr_files(repo_name, pr_number)
        except Exception as e:
            # 重新抛出异常，让上层处理
            raise e
        
        if not files:
            return "No files changed"
        
        # 动态调整合并层级
        max_depth = max(len(file.get('filename', '').split('/')) for file in files)
        optimal_depth = self._find_optimal_depth(files, max_depth)
        
        # 按最优层级分组
        dir_stats = self._group_files_by_depth(files, optimal_depth)
        
        # 构建统计信息
        stat_lines = []
        for dir_key, stats in dir_stats.items():
            total_additions = stats['total_additions']
            total_deletions = stats['total_deletions']
            file_count = stats['file_count']
            
            # 格式化目录统计
            if total_additions > 0 and total_deletions > 0:
                stat_line = f" {dir_key:<30} | {total_additions + total_deletions:>3} +{total_additions}-{total_deletions} ({file_count} files)"
            elif total_additions > 0:
                stat_line = f" {dir_key:<30} | {total_additions:>3} +{total_additions} ({file_count} files)"
            elif total_deletions > 0:
                stat_line = f" {dir_key:<30} | {total_deletions:>3} -{total_deletions} ({file_count} files)"
            else:
                stat_line = f" {dir_key:<30} |   0 ({file_count} files)"
            
            stat_lines.append(stat_line)
        
        return "\n".join(stat_lines)
    
    def _find_optimal_depth(self, files, max_depth):
        """
        找到最优的合并层级
        
        Args:
            files: 文件列表
            max_depth: 最大目录深度
            
        Returns:
            int: 最优层级
        """
        # 从2级开始尝试，逐步增加层级
        for depth in range(2, max_depth + 1):
            dir_stats = self._group_files_by_depth(files, depth)
            if len(dir_stats) > 1:
                return depth
        
        # 如果所有层级都只有1个分组，返回最大层级
        return max_depth
    
    def _group_files_by_depth(self, files, depth):
        """
        按指定深度分组文件
        
        Args:
            files: 文件列表
            depth: 目录深度
            
        Returns:
            dict: 分组统计信息
        """
        dir_stats = {}
        
        for file in files:
            filename = file.get('filename', '')
            additions = file.get('additions', 0)
            deletions = file.get('deletions', 0)
            
            # 获取指定深度的目录
            path_parts = filename.split('/')
            if len(path_parts) >= depth:
                dir_key = '/'.join(path_parts[:depth])
            else:
                dir_key = '/'.join(path_parts) if path_parts else "root"
            
            if dir_key not in dir_stats:
                dir_stats[dir_key] = {'total_additions': 0, 'total_deletions': 0, 'file_count': 0}
            
            dir_stats[dir_key]['total_additions'] += additions
            dir_stats[dir_key]['total_deletions'] += deletions
            dir_stats[dir_key]['file_count'] += 1
        
        return dir_stats

# 创建全局实例
# 从环境变量或配置文件中读取GitHub token
import os
github_token = os.getenv('GITHUB_TOKEN')
github_api = GitHubAPI(token=github_token)
