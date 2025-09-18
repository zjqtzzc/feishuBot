# GitHub PR 到飞书机器人通知系统

当GitHub仓库有新的Pull Request时，自动发送通知到飞书群聊。

## 功能特性

- 自动处理GitHub webhook事件
- 发送美观的飞书消息卡片
- 显示PR文件变更统计信息（智能合并层级）
- 支持GitHub webhook签名验证
- 完整的错误处理和日志记录
- 支持Ubuntu系统部署
- 模块化设计，GitHub API功能独立封装

## 快速部署

### 1. 安装环境

```bash
# 给脚本执行权限
chmod +x build.sh install.sh uninstall.sh

# 构建环境
./build.sh
```

### 2. 配置

编辑 `config.json` 文件：

```json
{
  "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/your-webhook-url",
  "github_token": "your-github-personal-access-token"
}
```

#### 获取GitHub Personal Access Token

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. 创建新Token，选择仓库和权限：
   - Contents: Read
   - Metadata: Read  
   - Pull requests: Read

### 3. 安装服务

```bash
sudo ./install.sh
```

### 4. 配置GitHub Webhook

1. GitHub仓库 → Settings → Webhooks → Add webhook
2. 设置：
   - Payload URL: `http://your-server:5000/webhook`
   - Content type: `application/json`
   - Events: 选择 "Pull requests"
   - Secret: 可选，用于签名验证

## 管理服务

```bash
# 启动服务
sudo systemctl start github-feishu-bot

# 停止服务
sudo systemctl stop github-feishu-bot

# 查看状态
sudo systemctl status github-feishu-bot

# 查看日志
sudo journalctl -u github-feishu-bot -f

# 卸载服务
sudo ./uninstall.sh
```

## API接口

- `GET /` - 服务信息
- `GET /health` - 健康检查
- `POST /webhook` - GitHub webhook接收接口

## 故障排除

### 查看日志

```bash
# 查看服务日志
sudo journalctl -u github-feishu-bot -f

# 查看应用日志
tail -f github-feishu-bot.log
```

### 常见问题

1. **服务启动失败**
   - 检查端口是否被占用：`sudo netstat -tlnp | grep 5000`
   - 检查配置文件是否正确

2. **GitHub API访问失败**
   - 检查token是否有效
   - 确认token有访问仓库的权限

3. **飞书消息发送失败**
   - 检查webhook URL是否正确
   - 确认飞书机器人已添加到群聊

## 项目结构

```
feishuBot/
├── app.py                    # 主应用文件
├── github_api.py            # GitHub API模块
├── config.json              # 配置文件
├── requirements.txt         # Python依赖
├── build.sh                 # 构建脚本
├── install.sh               # 安装脚本
├── uninstall.sh             # 卸载脚本
└── README.md                # 项目文档
```