# GitHub PR → 飞书卡片机器人

把 GitHub PR 的状态同步到飞书群：每个 PR 在群里对应一张卡片，PR 有动静时原地更新这张卡片。

卡片内容：

- 头部：PR 标题、状态标签（Open / Draft / Merged / Closed）、副标题「仓库 #号 · 作者」
- reviewer：待审（绑定过飞书的会 @）、通过、要求修改
- AI review：最新一轮的结论（AI 通过 / AI 不通过）和轮次
- CI：排队中 / 运行中 / 通过 / 失败（失败步骤、用时、日志链接）/ 已取消
- 改动文件：折叠面板，标题为改动合计，展开后按目录汇总
- 底部：分支、评论数、最近动态；「查看 PR」按钮
- 合并 / 关闭后收成一行

## 工作方式

- 收到 GitHub webhook 后先验签、立即返回，刷新交给后台单线程按顺序处理。
- 同一 PR 2.5 秒内的连续事件只刷新一次（防抖）。
- 卡片内容每次都从 GitHub 当前状态生成（PR、reviews、评论、改动文件、CI），不依赖事件顺序，丢事件也会在下一次刷新时补齐。
- 是否发卡片看 PR 状态：非 Draft、未关闭、还没有卡片时发新卡片，其余情况更新已有卡片；Draft 期间不发。
- 读取失败时：无权限（401 / 403 / 404）在卡片对应位置显示红字提示，不重试；网络错误、5xx、限流隔 30 秒重试，最多 2 次。
- 飞书卡片只能在发出后 14 天内更新；超期或被撤回 / 删除时，进行中的 PR 会重新发一张卡片。

## 目录

```
app.py                入口
src/server.py         HTTP 服务：接收 webhook、日志
src/handlers.py       webhook 验签与事件归类
src/worker.py         后台刷新：防抖、拉 GitHub 当前状态、发送 / 更新卡片
src/feishu_card.py    卡片渲染（飞书卡片 JSON 2.0）
src/github_api.py     GitHub REST API
src/feishu_api.py     飞书消息接口
src/feishu_credential.py  飞书 tenant_access_token
src/feishu_ws.py      飞书长连接：单聊命令
src/card_store.py     已发卡片记录（repo#pr → message_id）
src/user_map.py       GitHub 用户名 → 飞书用户映射
src/config.py         配置
scripts/preview_card.py  往指定群发示例卡片，检查排版
install.sh / uninstall.sh  安装、升级、回滚、卸载
```

## 配置

`config.json`（安装后位于 `output/data/config.json`，模板见 `config.json.example`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| `github_webhook_port` | 是 | 接收 GitHub webhook 的端口 |
| `github_token` | 是 | GitHub fine-grained token，权限见下文 |
| `github_webhook_secret` | 否 | webhook 的 Secret；留空则不校验签名（不建议） |
| `app_id` / `app_secret` | 是 | 飞书应用凭据 |
| `chat_id` | 是 | 发卡片的飞书群 id（`oc_` 开头） |

数据目录（配置、卡片记录 `.pr_event_store`、用户映射 `.user_map.json`）默认是项目根目录，可用环境变量 `BOT_DATA_DIR` 指定；systemd 服务指向 `output/data/`。

## GitHub 设置

**Webhook**（仓库或组织的 Settings → Webhooks）：

- Payload URL：`http://<服务器>:<github_webhook_port>/webhook`（`/` 也可以）
- Content type：`application/json`
- Secret：与 `github_webhook_secret` 一致
- 事件选 Let me select individual events，勾选：
  - Pull requests
  - Pull request reviews
  - Issue comments
  - Workflow jobs（CI 状态）

其他事件会被忽略。

**Token**（fine-grained personal access token），Repository permissions 只读：

- Metadata
- Pull requests
- Actions（CI 状态；fine-grained token 没有 Checks 权限，CI 通过 Actions 接口读取）

## 飞书应用设置

在飞书开放平台的应用后台：

- 开启机器人能力，并把机器人拉进 `chat_id` 对应的群
- 权限：以应用身份发消息；读取群成员（`!bind` 绑定自己时用来查飞书名字）；接收用户发给机器人的单聊消息
- 事件订阅：使用长连接接收事件，订阅「接收消息」（`im.message.receive_v1`）

权限的具体名称以开放平台上显示的为准。

## 单聊命令

私聊机器人（群聊消息会被忽略）：

| 命令 | 说明 |
|---|---|
| `!bind <GitHub 用户名>` | 把自己绑定到这个 GitHub 用户 |
| `!bind <GitHub 用户名> @某人` | 把 @ 的人绑定到这个 GitHub 用户 |
| `!unbind <GitHub 用户名>` | 删除绑定 |
| `!list` | 列出所有绑定 |
| `!help` | 帮助 |

绑定后，卡片里待审的 reviewer 会 @ 到对应的飞书用户。

## 安装与升级

需要 Python 3.10+、`python3-venv`、`rsync`。首次安装和升级都用同一个命令：

```bash
sudo ./install.sh
```

- 首次安装会生成 `output/data/config.json`，填好后再运行一次。
- 升级时新代码和依赖先装到旁边并验证（导入、配置、端口占用），验证失败线上不受影响；然后停服务、替换代码、启动并检查端口，启动失败自动回滚到上一版。
- 依赖没变时复用已有的虚拟环境；需要国内镜像时修改 `install.sh` 顶部的 `PIP_ARGS`。

```
output/app/       当前代码
output/app.prev/  上一版代码
output/venvs/     虚拟环境（按 requirements.txt 哈希）
output/venv       当前使用的虚拟环境
output/data/      配置与数据，升级永不覆盖
```

手动回滚到上一版：

```bash
sudo ./install.sh rollback
```

卸载（默认保留 `output/data/`，加 `--purge` 一并删除）：

```bash
sudo ./uninstall.sh
```

## 运维

查看日志（日志写入 systemd journal，由 journald 按空间自动轮转）：

```bash
sudo journalctl -u github-feishu-bot -f
```

往测试群发示例卡片，检查排版（在安装目录运行，读取线上配置）：

```bash
cd output/app && BOT_DATA_DIR=../data ../venv/bin/python scripts/preview_card.py <chat_id>
```

## 可调整的常量

| 常量 | 位置 | 说明 |
|---|---|---|
| `DEBOUNCE_SECONDS` | `src/worker.py` | 防抖时间，默认 2.5 秒 |
| `MAX_RETRIES` / `RETRY_DELAY_SECONDS` | `src/worker.py` | 重试次数与间隔 |
| `CI_EXCLUDE` | `src/feishu_card.py` | 不计入 CI 的 workflow / job（默认 `ai-review`） |
| `AI_REJECT_WORDS` | `src/feishu_card.py` | AI 结论里出现即判为不通过的词 |
| `MAX_FILE_GROUPS` | `src/feishu_card.py` | 改动文件明细最多显示的行数 |
| `CLOSED_TTL` / `CARD_TTL` | `src/card_store.py` | 合并 / 关闭后、发卡后保留卡片记录的时间 |
