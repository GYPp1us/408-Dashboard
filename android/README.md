# Mutsumi Focus Android

这是 408 Study Console 的 Android 壳层，首发只针对 Android 与 OriginOS；不包含华为系统适配。

## 能力与降级顺序

1. vivo 本地原子通知：在 vivo/iQOO 设备上写入官方 `notification.superx.*` 扩展字段。
2. Android 16 Live Update：使用 `Notification.ProgressStyle` 并请求 ongoing 通知推广；`FLAG_PROMOTED_ONGOING` 由系统批准后设置，未获推广时使用普通通知。
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
- WebView 仅在同一 HTTPS 主机和端口内导航，外链交给系统浏览器。
- APP 关闭 WebView 页面缩放及缩放控件，固定页面 viewport；指数图保留自身的手势操作。网页端仅在图表区域拦截浏览器的双指/Ctrl 加滚轮缩放，普通页面保留浏览器缩放。
- 主页表情图片上传通过 AndroidX Activity Result 调起系统图片单选，只读用户选择的 `content://` 图片，不申请图库或存储权限。取消、页面导航和 Activity 销毁会结束 WebView 文件回调；同时出现的新选择请求会被取消。
- `allowFileAccess=false` 和 `allowContentAccess=false` 保持不变：禁用的是页面直接加载本地 URL；用户通过文件输入明确选择的 URI 经独立的 WebView 文件选择回调传入。API 35 模拟器已通过实际系统选择器的 content URI 预览、原始图片上传、重载比例和取消保留原图；vivo 真机所用 WebView 的上传、取消及旋转屏幕行为仍待验证，范围见 [模拟器验证记录](../docs/android-emulator-validation.md)。
- 无障碍配置明确使用 `canRetrieveWindowContent=false`，代码不处理事件、不读取节点、不执行手势。
- 应用不使用全屏通知权限冒充电话或闹钟。
- 登录 Cookie 只用于同源心跳及暂停、继续、结束 API。

更完整的厂商限制与真机清单见 [OriginOS 说明](../docs/originos-atomic-island.md)。

文件选择边界的实现依据：Chromium 的 [`ShouldBlockURL`](https://github.com/chromium/chromium/blob/main/android_webview/browser/network_service/net_helpers.cc) 将 `allowContentAccess` 检查用于 `content://` 资源 URL；[`FilesSelectedInChooser`](https://github.com/chromium/chromium/blob/main/android_webview/browser/aw_web_contents_delegate.cc) 将用户选择的 URI 作为 `NativeFileInfo` 传给文件选择结果，未经过该 URL 检查；Android [`File::DoInitialize`](https://github.com/chromium/chromium/blob/main/base/files/file_posix.cc) 则通过 `OpenAndroidFile` 打开 content URI。因此保留上述两个开关，无需为文件输入开放页面的本地资源访问。API 35 模拟器结果支持这一实现，仍不能替代 vivo 真机验证。
