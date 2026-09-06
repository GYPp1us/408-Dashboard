# Mutsumi Focus Android

这是 408 Study Console 的 Android 壳层，首发只针对 Android 与 OriginOS；不包含华为系统适配。

## 能力与降级顺序

1. vivo 本地原子通知：在 vivo/iQOO 设备上写入官方 `notification.superx.*` 扩展字段。
2. Android 16 Live Update：使用 `Notification.ProgressStyle` 和 `FLAG_PROMOTED_ONGOING`。
3. Android 持续前台通知：所有 Android 8+ 设备均可使用，含继续、暂停、结束操作。
4. 超时提醒：优先使用应用悬浮层，其次使用不读取窗口内容的可选无障碍覆盖层，最后退化为高优先级通知。

没有 vivo 场景认证并不意味着全部不可用。本地通知调用、WebView、前台服务、心跳、通知操作、覆盖层提醒都不依赖 vivo 认证；但原子岛形态是否真正展示仍由系统按包名和 `scene` 权限判定。未授权时 `showNotify=true` 会保留普通通知兜底。

## 构建

环境要求：JDK 17+、Android SDK 36、Gradle Wrapper 9.6。Windows 下推荐把缓存放在 D 盘：

```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-21'
$env:ANDROID_HOME = 'D:\Android\Sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:GRADLE_USER_HOME = 'D:\GradleUserHome'
.\scripts\build_android.ps1 -Variant Debug
```

Release 必须使用可持续保管的独立签名：

```powershell
$env:MUTSUMI_FOCUS_STORE_FILE = 'D:\safe\mutsumi-focus-release.jks'
$env:MUTSUMI_FOCUS_STORE_PASSWORD = '<store password>'
$env:MUTSUMI_FOCUS_KEY_ALIAS = 'mutsumi-focus'
$env:MUTSUMI_FOCUS_KEY_PASSWORD = '<key password>'
.\scripts\build_android.ps1 -Variant Release
```

可在构建时覆盖站点和 vivo 获批场景：

```powershell
$env:MUTSUMI_FOCUS_URL = 'https://platform.arcol.site/'
$env:MUTSUMI_VIVO_ATOMIC_SCENE = '<vivo 分配的 scene>'
```

默认场景为诚实描述用途的 `FOCUS_TIMER`。它不是对 vivo 已授权的声明；获批前应预期普通通知降级。

## 隐私边界

- JavaScript 桥只接受计时状态，并将 `baseUrl` 固定为编译时域名。
- WebView 仅在同一 HTTPS 主机内导航，外链交给系统浏览器。
- 无障碍配置明确使用 `canRetrieveWindowContent=false`，代码不处理事件、不读取节点、不执行手势。
- 应用不使用全屏通知权限冒充电话或闹钟。
- 登录 Cookie 只用于同源心跳及暂停、继续、结束 API。

更完整的厂商限制与真机清单见 [OriginOS 说明](../docs/originos-atomic-island.md)。
