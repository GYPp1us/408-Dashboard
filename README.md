# 408 Study Console 个人部署指南

这是一个面向个人考研复习的横屏学习控制台，包含专注计时、学习窗口、月度热度图、模拟考趋势、访客只读面板和多设备状态同步。

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

## 8. 测试

```bash
cd /opt/408-dashboard/current
PYTHONPATH=. /opt/408-dashboard/venv/bin/python -m pytest tests/ -q
node --check app/static/app.js
```

## 9. 更新版本

```bash
cd /opt/408-dashboard/current
sudo git pull --ff-only origin main
sudo /opt/408-dashboard/venv/bin/pip install -r requirements.txt
PYTHONPATH=. /opt/408-dashboard/venv/bin/python -m pytest tests/ -q
node --check app/static/app.js
sudo systemctl restart 408-dashboard.service
sudo systemctl status 408-dashboard.service --no-pager -l
```

更新前建议先备份数据库。

## 10. 数据备份与恢复

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

## 11. 常用排查命令

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
