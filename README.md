# 408 Study Console

Desktop-first personal study dashboard for the Chinese postgraduate entrance exam.

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DASHBOARD_SECRET_KEY = "local-secret"
$env:DASHBOARD_ADMIN_PASSWORD = "local-password"
$env:DASHBOARD_DATABASE = ".\data\local.sqlite3"
$env:COOKIE_SECURE = "0"
.\.venv\Scripts\python.exe -m flask --app wsgi:app run --host 127.0.0.1 --port 43127
```

Run tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check app/static/app.js
```

## Production layout

- URL: `https://platform.arcol.site`
- App upstream: `127.0.0.1:43127`
- Deploy root: `/opt/408-dashboard`
- Current release: `/opt/408-dashboard/current`
- Shared environment: `/opt/408-dashboard/shared/app.env`
- Shared database: `/opt/408-dashboard/shared/data/dashboard.sqlite3`
- Service: `408-dashboard.service`

The app binds only to loopback. Nginx owns public ports `80` and `443`; port `43127` must not be exposed publicly.

The environment file must define `DASHBOARD_SECRET_KEY`, `DASHBOARD_ADMIN_PASSWORD`, `DASHBOARD_DATABASE=/opt/408-dashboard/shared/data/dashboard.sqlite3`, `DASHBOARD_HOST=127.0.0.1`, `DASHBOARD_PORT=43127`, `COOKIE_SECURE=1`, and `TZ=Asia/Shanghai`.
