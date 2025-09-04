# GitHub PR 到飞书机器人通知系统

当GitHub仓库有新的Pull Request时，自动发送通知到飞书群聊。

## 功能特性

- 🚀 自动处理GitHub webhook事件
- 📱 发送美观的飞书消息卡片
- 🔒 支持GitHub webhook签名验证
- 🛡️ 完整的错误处理和日志记录
- 🧪 提供测试接口验证连接
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
- `config.json` - 配置文件
- `config.json.example` - 配置示例
- `requirements.txt` - Python依赖
- `github-feishu-bot.service` - systemd服务配置
- `build.sh` - 构建脚本
- `install.sh` - 安装脚本
- `uninstall.sh` - 卸载脚本

### 2. 安装环境和配置

```bash
# 给脚本执行权限
chmod +x build.sh

# 运行构建脚本（普通用户权限）
./build.sh
```

### 3. 注册系统服务（可选）

```bash
# 给脚本执行权限
chmod +x install.sh

# 注册为系统服务（需要root权限）
sudo ./install.sh
```

### 4. 配置应用

安装脚本会自动引导你进行交互式配置：

1. **飞书webhook URL**（必填）
   - 在飞书群聊中创建自定义机器人
   - 复制webhook URL
   - 在安装时输入

2. **GitHub webhook密钥**（可选）
   - 为了安全，建议设置
   - 如果不需要，直接按回车跳过

### 5. 运行应用

安装完成后，你可以选择以下方式运行：

#### 方式1: 直接运行
```bash
python3 app.py
```

#### 方式2: 使用虚拟环境
```bash
source venv/bin/activate
python app.py
deactivate
```

#### 方式3: 系统服务（推荐）
```bash
sudo ./install.sh  # 注册为系统服务
```

## 卸载服务

如果需要完全卸载服务，可以使用卸载脚本：

```bash
# 给脚本执行权限
chmod +x uninstall.sh

# 运行卸载脚本（需要root权限）
sudo ./uninstall.sh
```

卸载脚本会执行以下操作：
- 停止并禁用systemd服务
- 删除systemd服务配置
- 删除logrotate配置
- 清理应用日志文件
- 清理systemd日志
- 保留虚拟环境和配置文件

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
   - **Payload URL**: `http://your-server-ip:5000/webhook`
   - **Content type**: `application/json`
   - **Secret**: 设置密钥（与config.json文件中的github_webhook_secret保持一致）
   - **Events**: 勾选"Pull requests"

## 服务管理

### 系统服务管理（如果已注册为服务）

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

### 手动运行管理

```bash
# 激活虚拟环境并运行
source venv/bin/activate
python app.py

# 后台运行
nohup python app.py > app.log 2>&1 &

# 查看进程
ps aux | grep app.py

# 停止后台进程
pkill -f app.py
```

## 端口配置

### 修改配置

1. 编辑配置文件：
```bash
sudo nano /path/to/your/project/config.json
# 修改相应的配置项
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
curl http://your-server:5000/health

# 发送测试消息到飞书
curl -X POST http://your-server:5000/test

# 测试webhook
curl -X POST http://your-server:5000/webhook \
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
sudo lsof -i :5000

# 杀死占用进程
sudo kill -9 <PID>
```

### 防火墙问题
```bash
# 检查防火墙状态
sudo ufw status

# 开放端口
sudo ufw allow 5000/tcp
```

## API接口

### 可用接口

- `GET /` - 服务信息
- `GET /health` - 健康检查
- `POST /test` - 发送测试消息到飞书
- `POST /webhook` - GitHub webhook接收接口

### 接口示例

```bash
# 获取服务信息
curl http://localhost:5000/

# 健康检查
curl http://localhost:5000/health

# 发送测试消息
curl -X POST http://localhost:5000/test
```

## 安全考虑

1. **防火墙配置**：只开放必要的端口（5000）
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
- `config.json`（项目目录中的配置文件）
- `/etc/systemd/system/github-feishu-bot.service`

## 许可证

MIT License