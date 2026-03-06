# -*- coding: utf-8 -*-
"""飞书 PR 消息卡片构建：按类型(open/merged/closed)生成对应颜色卡片"""

from github_api import GitHubAPITimeout

TYPE_TEMPLATE = {
    'open': 'blue',
    'merged': 'green',
    'closed': 'grey',
}

TYPE_TITLE = {
    'open': 'New Pull Request',
    'merged': 'PR Merged',
    'closed': 'PR Closed',
}


def build_pr_card(event_data: dict, card_type: str = 'open', github_api=None) -> dict:
    pr = event_data.get('pull_request', {})
    repo = event_data.get('repository', {})
    sender = event_data.get('sender', {})
    title = pr.get('title', '')
    url = pr.get('html_url', '')
    repo_name = repo.get('full_name', '')
    author_name = pr.get('user', {}).get('login', '')
    merger_name = sender.get('login', '')
    reviewers = [r.get('login', '') for r in pr.get('requested_reviewers', []) if r.get('login')]
    git_stat = ''
    if github_api:
        try:
            git_stat = github_api.format_git_file_stats(repo_name, pr.get('number', ''))
        except GitHubAPITimeout:
            git_stat = '⚠️ GitHub 连接超时，无法获取文件列表'
        except Exception:
            git_stat = '⚠️ GitHub 文件列表获取失败'
    lines = [f'**{title}**', '', git_stat, '', f'**提交人**: {author_name}', f'**Reviewer**: {", ".join(reviewers) or "暂无指定"}']
    if card_type == 'merged':
        lines.append(f'**合并者**: {merger_name}')
    template = TYPE_TEMPLATE.get(card_type, 'blue')
    header_title = f'{repo_name}: {TYPE_TITLE.get(card_type, "Pull Request")}'
    return {
        'msg_type': 'interactive',
        'card': {
            'header': {'template': template, 'title': {'content': header_title, 'tag': 'plain_text'}},
            'elements': [
                {'tag': 'div', 'text': {'content': '\n'.join(lines), 'tag': 'lark_md'}},
                {'tag': 'action', 'actions': [{'tag': 'button', 'text': {'content': '查看PR', 'tag': 'plain_text'}, 'type': 'primary', 'url': url}]}
            ]
        }
    }
