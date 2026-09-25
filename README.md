# 408 Study Console 个人部署指南

这是一个面向个人考研复习的横屏学习控制台，包含专注计时、学习窗口、月度热度图、模拟考趋势、访客只读面板和多设备状态同步。

## Android / OriginOS 预览版

仓库的 `android/` 目录包含 Android 8+ 客户端。它复用网页界面，并增加前台计时、后台心跳、通知操作、暂停/离开超时覆盖提醒，以及 vivo 本地原子通知和 Android 16 Live Update 的尽力适配。未获 vivo 场景认证时会降级为普通持续通知，不影响核心计时与提醒功能；不包含华为适配。

构建、权限与无认证边界见 [Android README](android/README.md) 和 [OriginOS 原子岛说明](docs/originos-atomic-island.md)。

本文以 Ubuntu、systemd、Nginx 和自有域名为例。应用只监听服务器回环地址，由 Nginx 提供公网 HTTP/HTTPS 服务。

## 1. 部署前准备

需要准备：

- 一台支持 systemd 的 Linux 服务器；
- Python 3.10 或更高版本；
- Nginx；
- Git；
- 一个已解析到服务器的域名；
- 开放公网 `80` 和 `443` 端口。

安装基础软件：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv nginx sqlite3
```

## 2. 安装应用

```bash
sudo mkdir -p /opt/408-dashboard/shared/data
sudo git clone https://github.com/GYPp1us/408-Dashboard.git /opt/408-dashboard/current
sudo python3 -m venv /opt/408-dashboard/venv
sudo /opt/408-dashboard/venv/bin/pip install -r /opt/408-dashboard/current/requirements.txt
```

数据库会在首次启动时自动创建。专注记录、成绩和设置都保存在共享数据目录中。

## 3. 配置环境变量

生成随机会话密钥：

```bash
openssl rand -hex 32
```

创建 `/opt/408-dashboard/shared/app.env`：

```dotenv
DASHBOARD_SECRET_KEY=替换为上一步生成的随机值
DASHBOARD_ADMIN_PASSWORD=替换为管理员密码
DASHBOARD_DATABASE=/opt/408-dashboard/shared/data/dashboard.sqlite3
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=43127
COOKIE_SECURE=1
TZ=Asia/Shanghai
```

设置权限：

```bash
sudo chown -R www-data:www-data /opt/408-dashboard/shared/data
sudo chown root:www-data /opt/408-dashboard/shared/app.env
sudo chmod 640 /opt/408-dashboard/shared/app.env
```

不要把 `app.env`、数据库或备份文件提交到 Git。

## 4. 配置 systemd

仓库已经提供服务文件：

```bash
sudo cp /opt/408-dashboard/current/systemd/408-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now 408-dashboard.service
sudo systemctl status 408-dashboard.service --no-pager -l
```

确认本机上游可访问：

```bash
curl -I http://127.0.0.1:43127/login
```

Gunicorn 只监听 `127.0.0.1:43127`。不要在防火墙中公开此端口。

## 5. 配置 Nginx

复制仓库中的配置，并将 `platform.arcol.site` 替换为自己的域名：

```bash
sudo cp /opt/408-dashboard/current/deploy/nginx-platform.arcol.site.conf /etc/nginx/sites-available/408-dashboard
sudo sed -i 's/platform\.arcol\.site/study.example.com/g' /etc/nginx/sites-available/408-dashboard
sudo ln -sfn /etc/nginx/sites-available/408-dashboard /etc/nginx/sites-enabled/408-dashboard
sudo nginx -t
sudo systemctl reload nginx
```

此时可以先通过 `http://study.example.com` 检查 Nginx 反向代理，但不建议长期使用 HTTP。

## 6. 启用 HTTPS

安装 Certbot 并申请 Let's Encrypt 证书：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d study.example.com
```

Certbot 会在 Nginx 中加入证书配置，并可自动将 HTTP 重定向到 HTTPS。

完成后访问 `https://study.example.com/`。未登录访问会自动进入无密码访客面板；点击右上角“管理员”或直接访问 `https://study.example.com/admin` 后，输入管理员密码进入管理界面。

## HTTP 与 HTTPS 的区别

| 项目 | HTTP | HTTPS |
| --- | --- | --- |
| 传输安全 | 密码和页面数据可能被同网络中的设备读取或篡改 | 浏览器与服务器之间的数据经过 TLS 加密 |
| `COOKIE_SECURE` | 必须设为 `0`，否则浏览器不会回传登录 Cookie | 应设为 `1` |
| 屏幕持续唤醒 | 普通 HTTP 域名或局域网 IP 通常不可用 | 支持 Screen Wake Lock API 的浏览器可用 |
| 浏览器安全 API | 多个 API 会被限制；`localhost` 是部分例外 | 被视为安全上下文，可使用更多现代 API |
| 推荐用途 | 仅限本机开发或可信局域网临时测试 | 公网部署和日常使用 |

公网部署必须使用 HTTPS。项目中的持续唤醒功能依赖安全上下文；即使页面其他功能在 HTTP 下可以打开，唤醒锁也可能无法申请。

如果通过 HTTP 部署却设置了 `COOKIE_SECURE=1`，常见表现是密码正确但登录后又返回登录页。原因是浏览器不会通过 HTTP 发送带有 `Secure` 标记的会话 Cookie。

Nginx 到 Gunicorn 的内部连接仍然可以使用 `http://127.0.0.1:43127`。该连接只经过服务器本机回环接口，公网 HTTPS 在 Nginx 处终止。

## 7. 本机 HTTP 调试

Windows PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DASHBOARD_SECRET_KEY = "local-secret"
$env:DASHBOARD_ADMIN_PASSWORD = "local-password"
$env:DASHBOARD_DATABASE = ".\data\local.sqlite3"
$env:COOKIE_SECURE = "0"
.\.venv\Scripts\python.exe -m flask --app wsgi:app run --host 127.0.0.1 --port 43127
```

打开 `http://127.0.0.1:43127`。浏览器通常会把 `localhost` 和 `127.0.0.1` 视为本地可信环境，但通过 `http://192.168.x.x` 等局域网地址访问时，持续唤醒等 API 仍可能被禁用。

## 8. 数据迁移

管理员可以在设置页生成一次性迁移码。总服务器使用该迁移码拉取完整学习数据：

```http
GET /api/migration/export
X-Migration-Code: <一次性迁移码>
```

迁移码有效期为 15 分钟，成功拉取后立即失效。接口返回版本化 JSON 数据包，包含设置、科目、专注事项、全部专注与暂停记录、成绩和计划，不包含管理员密码或登录会话。生产环境必须通过 HTTPS 调用该接口。

### 外部专注上报

登录后在设置页“外部专注上报”复制上报链接或接入提示。链接中的 key 是长期有效的账户凭据，不会因服务重启、版本更新或应用密钥轮换而失效；只有主动“更换 key”才会立即撤销旧链接。45 秒是专注会话的断联超时，并非 key 有效期。`GET <catalog_url>` 返回当前账户的科目与事项 ID。上报者每 10–30 秒向 `<report_url>` 发送一个 JSON 状态帧，停止时立即发送 `idle`：

```json
{"source":"study_app","state":"focus","subject_id":1,"focus_item_id":1}
```

`source` 是每个软件固定的 1–64 位字母、数字、点、下划线或短横线标识；两个 ID 须从目录接口获取且属于同一科目。连续 `focus` 帧只续同一段专注，事项变化会自动分段。超过 45 秒没有上报就按最后一帧后 45 秒结束；计时使用服务器接收时间。已有另一处专注或当日已结算时返回 HTTP 409。

## 9. 测试

```bash
cd /opt/408-dashboard/current
PYTHONPATH=. /opt/408-dashboard/venv/bin/python -m pytest tests/ -q
node --check app/static/app.js
```

## 10. 更新版本

涉及“科目—专注事项”层级迁移的版本，在切换候选 release 前、**重启服务前**必须完成只读预检。预检发现任意 `blocking` 或 `review` 风险时会以退出码 `2` 结束；此时不要迁移、重启或切换 release，保留 JSON 给负责人审查：

预检通过或 review 项获得明确批准后，再做在线备份和演练迁移。完整的风险定义、备份、演练和审批证据要求见 [科目—专注事项层级迁移审查清单](docs/stable-subject-migration-review.md)。

对于层级迁移版本，下面的 `restart` 不能直接执行：先依照审查清单停止服务，用 `scripts/migrate_subject_schema.py` 在单个 Python 进程中完成实际迁移、确认其 JSON 中 `foreign_key_check` 为空，再启动服务。

```bash
set -euo pipefail
cd /opt/408-dashboard/releases/<candidate-release>
sudo git pull --ff-only origin main
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/preflight_subject_migration.py \
  /opt/408-dashboard/shared/data/dashboard.sqlite3 --json
sudo /opt/408-dashboard/venv/bin/pip install -r requirements.txt
PYTHONPATH=. /opt/408-dashboard/venv/bin/python -m pytest tests/ -q
node --check app/static/app.js
# 层级迁移版本：此处停止；按审查清单完成备份、演练、单进程迁移与批准后，才可切换 release 并启动服务。
```

更新前建议先备份数据库。

## 11. 数据备份与恢复

在线备份：

```bash
sudo mkdir -p /opt/408-dashboard/shared/backups
sudo sqlite3 /opt/408-dashboard/shared/data/dashboard.sqlite3 \
  ".backup /opt/408-dashboard/shared/backups/dashboard-$(date +%Y%m%d-%H%M%S).sqlite3"
```

恢复前先停止服务：

```bash
sudo systemctl stop 408-dashboard.service
sudo cp /opt/408-dashboard/shared/backups/选定的备份.sqlite3 \
  /opt/408-dashboard/shared/data/dashboard.sqlite3
sudo chown www-data:www-data /opt/408-dashboard/shared/data/dashboard.sqlite3
sudo systemctl start 408-dashboard.service
```

## 12. 常用排查命令

```bash
systemctl status 408-dashboard.service --no-pager -l
journalctl -u 408-dashboard.service --since -10min --no-pager -l
nginx -t
curl -I http://127.0.0.1:43127/login
curl -I https://study.example.com/login
```

出现移动端功能差异时，优先确认：

1. 页面是否通过 HTTPS 打开；
2. Android Chrome 或 System WebView 是否为较新版本；
3. 页面是否保持在浏览器前台；
4. 系统省电策略是否强制释放屏幕唤醒锁。
