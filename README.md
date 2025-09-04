# GitHub PR 到飞书机器人通知系统

当GitHub仓库有新的Pull Request时，自动发送通知到飞书群聊。

## 功能特性

- 🚀 自动处理GitHub webhook事件
- 📱 发送美观的飞书消息卡片
- 🔒 支持GitHub webhook签名验证
- 🛡️ 完整的错误处理和日志记录
- 🐧 支持Ubuntu系统部署

## 系统架构

```
GitHub Repository → GitHub Webhook → Ubuntu Server → 飞书机器人 → 飞书群聊
```

## 环境要求

- Ubuntu 18.04+ 
- Python 3.6+
- pip3
- python3-venv
- systemd

### 安装依赖

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

## 快速部署

### 1. 下载项目文件

将以下文件上传到Ubuntu服务器：
- `app.py` - 主应用文件
- `config.py` - 配置文件
- `requirements.txt` - Python依赖
- `github-feishu-bot.service` - systemd服务配置
- `deploy.sh` - 部署脚本
- `config.example` - 配置示例

### 2. 运行部署脚本

```bash
# 给脚本执行权限
chmod +x deploy.sh

# 运行部署脚本（需要root权限）
sudo ./deploy.sh
```

### 3. 配置环境变量

编辑环境变量文件：
```bash
sudo nano /opt/github-feishu-bot/.env
```

设置以下变量：
```bash
# 飞书机器人webhook URL（必填）
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your-webhook-url

# GitHub webhook密钥（可选，用于验证webhook签名）
GITHUB_WEBHOOK_SECRET=your-github-webhook-secret

# 服务配置
PORT=8080
FLASK_ENV=production
LOG_LEVEL=INFO
```

### 4. 重启服务

```bash
sudo systemctl restart github-feishu-bot
```

## 配置飞书机器人

1. 在飞书群聊中，点击右上角设置
2. 选择"群机器人" → "添加机器人"
3. 选择"自定义机器人"
4. 填写机器人名称和描述
5. 复制webhook URL到环境变量中

## 配置GitHub Webhook

1. 打开GitHub仓库 → Settings → Webhooks
2. 点击"Add webhook"
3. 配置如下：
   - **Payload URL**: `http://your-server-ip:8080/webhook`
   - **Content type**: `application/json`
   - **Secret**: 设置密钥（与.env文件中的GITHUB_WEBHOOK_SECRET保持一致）
   - **Events**: 勾选"Pull requests"

## 服务管理

```bash
# 启动服务
sudo systemctl start github-feishu-bot

# 停止服务
sudo systemctl stop github-feishu-bot

# 重启服务
sudo systemctl restart github-feishu-bot

# 查看服务状态
sudo systemctl status github-feishu-bot

# 查看服务日志
sudo journalctl -u github-feishu-bot -f
```

## 端口配置

### 修改端口

1. 编辑环境变量文件：
```bash
sudo nano /opt/github-feishu-bot/.env
# 修改 PORT=9000
```

2. 重启服务：
```bash
sudo systemctl restart github-feishu-bot
```

3. 更新防火墙规则（如果使用ufw）：
```bash
sudo ufw allow 9000/tcp
sudo ufw delete allow 8080/tcp
```

### 测试服务

```bash
# 健康检查
curl http://your-server:8080/health

# 测试webhook
curl -X POST http://your-server:8080/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -d '{"action":"opened","pull_request":{"title":"Test PR"}}'
```

## 故障排除

### 服务启动失败
```bash
# 查看服务状态
sudo systemctl status github-feishu-bot

# 查看日志
sudo journalctl -u github-feishu-bot -n 50
```

### 端口被占用
```bash
# 查看端口占用
sudo lsof -i :8080

# 杀死占用进程
sudo kill -9 <PID>
```

### 防火墙问题
```bash
# 检查防火墙状态
sudo ufw status

# 开放端口
sudo ufw allow 8080/tcp
```

## 安全考虑

1. **防火墙配置**：只开放必要的端口（8080）
2. **HTTPS**：生产环境建议配置SSL证书
3. **访问控制**：可以配置防火墙限制访问IP
4. **日志轮转**：配置logrotate防止日志文件过大

## 更新和维护

### 更新应用
1. 备份当前版本
2. 上传新版本文件
3. 重启服务

### 备份配置
重要文件：
- `/opt/github-feishu-bot/.env`
- `/etc/systemd/system/github-feishu-bot.service`

## 许可证
MIT License
