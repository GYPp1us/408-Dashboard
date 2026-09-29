# Android 模拟器验证

本记录覆盖 Android 15/API 35 和 Android 16/API 36 模拟器。状态、通知和交互矩阵使用独立数据库、localhost HTTPS 和 Debug 专用 CA；最终签名包仅连接生产站点进行只读升级验收，不写生产测试数据。模拟器结果不代表 vivo/OriginOS 真机或厂商原子岛认证结果。

## 已读取的结果

以下 JSON 是 2026-09-29 实际读取的测试产物，存于被 Git 忽略的 `.tmp`。通过项以 JSON 中的 `passed: true` 为依据。Debug 状态矩阵与最终签名包的只读升级验收分别记录。

| 环境 | 结果文件 | 已通过范围 |
| --- | --- | --- |
| API 35 | `.tmp/android-interactions-results.json`，13 项 | 竖屏顺序与无溢出、横屏三列无溢出、短触不打开详情、移动取消长按、专注事项/表情包/指数左侧半屏详情与原生返回、热度长按、图表切换、打开详情后旋转保持状态、账户路由、设置/账户旋转、无 WebView JS 错误 |
| API 35 | `.tmp/android-artwork-results.json`，9 项 | 实际系统选择器的 content URI 预览、原始图片上传、重载保持原比例且无 max-width 限制、取消保留原图、选择器旋转后取消保持详情窗、导航丢弃旧回调、再次打开、恢复默认图、无 JS 错误 |
| API 35 | `.tmp/android-notifications-results.json`，16 项 | 通知权限拒绝与允许、持续计时；实际通知暂停/继续/结束与服务端及本地状态一致；网页暂停与页面覆盖层继续；后台心跳；暂停 5 分钟提醒及点击；结束 15/30/60 分钟逐级确认；最后一次确认后服务和通知停止；休息无提醒；无 WebView 运行异常 |
| API 35 | `.tmp/android-recovery-results.json`，10 项 | 账户子路由保存、横竖屏无溢出、进程重启和 Activity 重建恢复精确路由、主题和快捷数量保存、原生返回关闭录分详情、离线重启保留路由和原生暂停计时、重连保持路由并继续专注 |
| API 35 | `.tmp/android-identity-results.json`，9 项 | 本人设置刷新保留账户路由及草稿、暂停状态同步、访客无心跳及原生通知、访客图片只读、返回本人状态、真实登出及失效 Cookie 清理 |
| API 35 | `.tmp/android-overlay-results.json`，7 项 | 真实应用悬浮窗口、红色按钮短触不确认、右滑延后提醒、遮罩打开计时器、真实无障碍覆盖窗口兜底及右滑确认、回到空闲；测试后恢复权限 |
| API 35 | `.tmp/android-boot-offline-results.json`，7 项 | 两轮离线缓存和重连保持精确账户路由；实际设备重启后开机接收器恢复暂停计时、前台通知及同一会话，无需先打开 Activity；返回精确子路由 |
| API 35 | `.tmp/chart-zoom-results.json`，2 项 | 真实双指缩放只改变指数图范围，整页尺度保持 0.5；图表外双指操作不能缩放页面 |
| 桌面浏览器 | `.tmp/chart-zoom-browser-results.json`，2 项 | 实际 Ctrl 加滚轮改变图表范围而不缩放页面；缩放守卫仅作用于图表区域，普通网页保留浏览器缩放 |
| API 36 | `.tmp/api36/android-interactions-results.json`，13 项 | 同 API 35 的交互矩阵：横竖屏、长按详情、返回、移动取消、图表、账户路由和 JS 错误检查 |
| API 36 | `.tmp/api36/android-notifications-results.json`，17 项 | 同 API 35 的通知操作和提醒矩阵；额外观察到 ProgressStyle。该设备 `promotedOngoing: false`，不能据此声称通知已获实时推广 |
| API 36 | `.tmp/api36/android-recovery-results.json`，10 项 | 精确账户路由、横竖屏、进程及 Activity 重建、主题/快捷数量保存、返回关闭详情、离线缓存与重连继续 |
| API 36 | `.tmp/api36/android-identity-results.json`，9 项 | 本人非主页同步不覆盖路由及草稿，访客只读与无心跳，真实退出及 Cookie 失效清理原生计时/通知 |
| API 36 | `.tmp/api36/android-reminder-session-results.json`，3 项 | 两个连续暂停会话的同类提醒正确更换 session ID；实际点击新提醒能够延后且撤销通知，旧提醒不阻塞新会话 |
| API 36 | `.tmp/api36/android-expired-notification-results.json`，2 项 | 原生 Cookie 失效后点击真实通知暂停按钮，服务端实际返回 401，1172 ms 内清除计时状态及两类通知，无需等待下一次心跳；无 JS 错误 |
| API 36 | `.tmp/api36/android-lockscreen-results.json`，3 项 | 实际锁屏 120569 ms，原生前台服务持续发送心跳；同一会话保持 active 且未结束，数据库心跳时间实际推进约两分钟，无 JS 错误 |
| API 36 | `.tmp/api36/android-final-smoke-results.json`，4 项 | 新模板固定 native viewport；图表 Ctrl 加滚轮守卫；正式候选请求通知推广并保留 ProgressStyle；无 WebView 异常 |
| API 36 | `.tmp/api36/chart-zoom-results.json`，3 项 | 真实双指最终缩放范围保留、页面比例不变；双指尾部不会误触日期重建，下一次单指点击仍可回看历史日期 |

提醒时间边界通过隔离夹具构造真实暂停/结束时间，再由原生策略、实际通知及悬浮 UI 执行确认；锁屏两分钟和设备重启使用真实经过时间和真实系统操作。API 36 镜像没有独立通知推广设置入口，因此验证普通通知兜底，不声称系统已批准 Live Update 推广。

## 隔离夹具

源文件为 [`scripts/android_fixture_server.py`](../scripts/android_fixture_server.py)，控制路由只在该脚本的 `fixture_app()` 中注册。正常 `app.create_app()` 不注册 `/_test/info` 或 `/api/_test/scenario`；自检也验证这一点。生产 WSGI、部署服务和应用模块不得导入或启动此夹具。

- `--db` 经真实路径解析后必须是本仓库 `.tmp` 直属目录下的 `.sqlite3` 文件；不能指向 `data`、目录外或符号链接指向的外部目标。
- `serve --host` 只接受 `localhost`、`127.0.0.1`、`::1`，拒绝 `0.0.0.0` 和局域网/公网地址。
- `scenario --url` 只接受 HTTP(S) 的上述主机，不接受 URL 内凭据；重定向也再次检查 loopback，避免测试账号信息被转发到外部地址。
- 使用固定测试账号 `androidowner`、`androidviewer`，密码均为 `Emulator-only-2026`。`/androidowner/guest` 为只读访客入口。固定密码和测试密钥仅供此本地夹具使用。
- 调整场景必须正常登录，访客返回 403，匿名返回 401；只修改该测试账号的专注记录和当日结算，保留其他账号、偏好和图片。
- 夹具保留真实服务端规则：前台超时 30 秒、监测间隔 500 ms；暂停仍是 `status=active`，不被该超时结束；手动结束使用原有结束 helper 并关闭暂停记录。休息只存在于网页/原生状态。

从仓库根目录执行自检；它不启动监听服务：

```powershell
.venv\Scripts\python.exe scripts/android_fixture_server.py selfcheck --db .tmp/android-fixture-documentation-test.sqlite3
```

本轮该自检已通过 loopback/URL/数据库限制、生产无控制路由、正常登录/开始/暂停/继续/结束、九种加速场景和 401/403 边界。

需要交互验证时由操作者启动服务并保留终端日志：

```powershell
.venv\Scripts\python.exe scripts/android_fixture_server.py serve --host 127.0.0.1 --port 43128 --cert .tmp/android-test-cert.pem --key .tmp/android-test-key.pem --db .tmp/android-emulator-test.sqlite3
D:\Android\Sdk\platform-tools\adb.exe -s emulator-5556 reverse tcp:43128 tcp:43128
```

证书和私钥在 `.tmp` 中另行准备，未提交。Debug 测试构建使用 `MUTSUMI_FOCUS_URL=https://localhost:43128/` 和 `MUTSUMI_FOCUS_TEST_RES=.tmp/android-test-res` 中的专用 CA；只在测试进程设置这些变量，Release 使用生产 HTTPS 地址和独立签名。API 36 操作时将序列号替换为相应设备。

## 状态和时间边界复现

常规按钮保持调用现有 `/api/focus/start`、`/api/focus/pause`（`paused: true/false`）、`/api/focus/end`。测试先从 `/api/dashboard.focus_items` 取当前账号事项 ID，检查服务端响应、WebView UI、原生保存状态和通知四方一致。

加速场景支持 `idle`、`focusing`、`paused`、`paused5min`、`ended`、`ended15min`、`ended30min`、`ended60min`、`rest`：

```powershell
.venv\Scripts\python.exe scripts/android_fixture_server.py scenario --url https://localhost:43128 --insecure --scenario paused5min --seconds-before 5
.venv\Scripts\python.exe scripts/android_fixture_server.py scenario --url https://localhost:43128 --insecure --scenario ended15min
```

`--seconds-before 5` 让边界在五秒后到达，默认 `-2` 为已逾期两秒；`--user androidviewer` 切换测试账号。`--insecure` 仅用于本地自签名证书。每次命令独立登录并输出真实 `session` 和匹配的 `native_state`。

在已登录测试 WebView 的 CDP 中可构造并注入匹配时间：

```javascript
const response = await fetch('/api/_test/scenario', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({scenario: 'paused5min', seconds_before: 5})
});
if (!response.ok) throw new Error(`fixture_${response.status}`);
const fixture = await response.json();
window.MutsumiAndroid.syncFocusState(JSON.stringify(fixture.native_state));
```

结束场景先正常结束当前 UI 专注并等待轮询收敛，再构造并注入 `native_state`。仅回写数据库 `ended_at` 不够：网页/原生结束转换记录的是发现结束的时间。结束 30/60 分钟场景必须依次确认此前的 15/30 分钟提醒；策略始终先展示最早未确认提醒。加速只改变隔离测试状态，不改变生产提醒规则。

## 实时系统 UI 快照

[`LiveUiSnapshot.java`](../scripts/android/LiveUiSnapshot.java) 通过 shell `app_process` 建立新的 UiAutomation 连接，清空缓存并直接读取当前活动树，避免动态计时导致 `uiautomator dump` 无法等到 idle。无当前 root 时最多重试一秒后以非零退出，不读取或沿用旧 XML。

```powershell
.\scripts\android\build-live-ui.ps1 -Serial emulator-5556
# 仅编译，不推送设备：加 -NoPush
D:\Android\Sdk\platform-tools\adb.exe -s emulator-5556 shell "CLASSPATH=/data/local/tmp/live-ui-helper.jar app_process /system/bin LiveUiSnapshot dump"
D:\Android\Sdk\platform-tools\adb.exe -s emulator-5556 shell "CLASSPATH=/data/local/tmp/live-ui-helper.jar app_process /system/bin LiveUiSnapshot dump-windows"
D:\Android\Sdk\platform-tools\adb.exe -s emulator-5556 shell "CLASSPATH=/data/local/tmp/live-ui-helper.jar app_process /system/bin LiveUiSnapshot find-text '继续专注' --package com.android.systemui"
```

构建依赖 JDK 21、SDK android-36、build-tools 36.0.0，可传入 `-Jdk` 和 `-Sdk`；生成 classes/dex/jar 全在 `.tmp/android-ui`，jar 推到设备 `/data/local/tmp/live-ui-helper.jar`。javac、d8、jar 或 adb 失败会立即抛错停止；不存在依赖也会停止。

输出包括 `capturedAtEpochMs`、`completedAtEpochMs`、活动 root、窗口元数据、节点 text/resourceId/package/bounds 和 `nodeCount`。解析 JSON 后再核对当前通知栏的 SystemUI root/窗口和时间。保存输出后必须检查 `$LASTEXITCODE`，失败产物不得作为新快照使用。

`dump-windows` 单独输出每个当前窗口的元数据和实时 root，不再重复输出活动 root。新 UiAutomation 连接尚未收到窗口树时，最多等待一秒，每次清缓存并重新读取 getWindows；JSON 的 `windowRootRetries` 记录次数，超时无实时 root 仍非零退出，绝不复用旧数据。应用悬浮层与无障碍覆盖层使用 `FLAG_NOT_FOCUSABLE` 时，活动 root 可能仍为底层 launcher；此时从 windows 中的真实覆盖层节点读取 bounds。普通 `dump` 和查找/点击模式仍只遍历活动树，单一精确匹配安全规则不变。

只有负责当前 UI 流程的操作者执行点击：将 `find-text` 改为 `tap-text`，或使用 `find-id`/`tap-id`。工具要求一个可见的精确匹配，多匹配或禁用节点拒绝点击；优先点击最近的可点击祖先，否则按节点 bounds 中心注入触摸。该 shell 工具与应用的无障碍服务无关，不会改变应用的 `canRetrieveWindowContent=false` 隐私边界。

工具还提供显式双指手势，仅在调用 `pinch centerX centerY startSpan endSpan durationMs` 时注入。坐标和 span 均为设备物理屏幕像素，不是 WebView CSS 像素；两指位于中心左右，沿水平方向改变间距。操作者先确认目标图表实际 bounds，再选择全部落在屏幕和目标内的参数，例如：

```powershell
D:\Android\Sdk\platform-tools\adb.exe -s emulator-5556 shell "CLASSPATH=/data/local/tmp/live-ui-helper.jar app_process /system/bin LiveUiSnapshot pinch 540 1200 120 360 500"
```

中心坐标范围 0–8192，span 范围 16–4096，左右端点必须保持在 0–8192，时长为 100–3000 ms。工具发出真实 DOWN、POINTER_DOWN、多次双指 MOVE、POINTER_UP、UP；注入失败仍尝试释放两指。JSON 的 `pinch.parameters`、`actualDurationMs`、`eventCount`、`injected` 和 `failedEvents` 记录结果，任一注入失败以非零退出。普通 dump/find/tap 模式不会执行 pinch。

缩放验收由操作者在实际手势前后读取 WebView `visualViewport.scale`，确认页面尺度保持不变，同时单独核对指数图等图表的内部交互。工具的构建和推送不等于手势或缩放验收通过。

## 最终包边界检查

最终 APK 为 `Mutsumi-Focus-v0.3.0.apk`，版本码 3，SHA-256 为 `158a3364523084c75895c25443f95b1b9a19182b3ada809d9bb5b62fe14d1a64`。发布证书 SHA-256 为 `8fb58fd11708b42567aadfecc2c570f643d0f4fb9634d7a7e8a9059b27a42f52`，与 v0.2.0 一致。生产地址为 `https://platform.arcol.site/`，包内不含 localhost 测试地址或模拟器测试 CA。

API 36 已实际安装官方 v0.2.0 后以 `install -r` 升级最终 APK，未卸载应用；生产只读访客路由 `/guest` 保留，冷启动仍回到该路由。签名、版本、包标志、哈希和页面截图保存在 `.tmp/api36`。状态及写入矩阵仍全部使用上述隔离数据库。

Release APK 的 `DEBUGGABLE` 标志不存在，`BuildConfig.DEBUG=false`，应用显式调用 `setWebContentsDebuggingEnabled(false)`。API 36 镜像为 `userdebug`/`ro.debuggable=1`，其 WebView 仍暴露调试 socket；这不能记为“模拟器已关闭 CDP”。[Chromium 官方源码](https://chromium.googlesource.com/chromium/src/+/71d81bd2623fc6cc6c59198e2f72cf0df6b38b9b/android_webview/glue/java/src/com/android/webview/chromium/SharedStatics.java) 在 Android 系统 debug build 上直接忽略该开关，调试由 provider 强制启用。应用禁用配置已核验，普通 user ROM 的 socket 行为及 vivo 真机仍待实测。

本人非主页刷新、访客身份隔离、真实登出/401 清理、账户休息隔离、重复离线恢复和图片回调边界均见上表及自动回归。Python 158 项、前端边界 14 项、Android 单元测试 14 项，Debug/Release lint 与生产签名构建均通过。
