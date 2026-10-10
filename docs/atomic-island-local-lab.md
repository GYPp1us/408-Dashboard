# 本地原子岛实验

工作分支：`codex/atomic-island-local`。目标：用户自己的 iQOO 15，计划升级 OriginOS 7。已连接并测试当前 OriginOS 6；以下不代表上岛成功或已绕过厂商权限。

## 真机结果与权限判断

设备实际返回：型号 `V2505A`，Android 16/API 36，`OriginOS 6`，构建 `PD2505B_A_16.0.30.14.W10`。ADB 会话为 UID 2000（shell），`ro.build.type=user`；没有找到 PATH 中的 `su`，但用户尚未确认 root 状态。

| 实验 | 当前证据 |
| --- | --- |
| 普通通知 | 用户已开启通知，普通通知可显示 |
| 完整模板 + `FOCUS_TIMER` | 通知已发送，主页没有岛；无岛回执 |
| 完整模板 + `TAKEOUT` | 系统记录 `SUPERX_VALUE=false`，已清除原子通知数据块，保留普通通知 |
| 历史 `islandNotify=true` | 系统记录 `SUPERX_VALUE=false`，保留历史标记而剔除原子通知数据；主页没有岛 |
| Android 16 实时通知 | 用户手动试过后可见普通通知；`canPostPromotedNotifications=false`，系统无可解析的 APP_NOTIFICATION_PROMOTION_SETTINGS 入口。该项未完成独立的升级后验收 |
| 官方 demo 测试包名 | APK 已构建；手机端安装最终返回 `INSTALL_FAILED_ABORTED: User rejected permissions`，尚未安装和测试。用户表示没有主动点击拒绝，并要求稍等，已暂停手机操作 |

只读提取了本机 framework、services、vivo-framework、vivo-services 及 SystemUI，原件位于 `E:/CodexBuild/408-Dashboard-atomic-island/firmware-PD2505B-A-16.0.30.14/`。反汇编和截图位于忽略目录 `.tmp/atomic-island-lab/device/`。

已核实的调用链：

1. `NotificationManager.setSuperXInfosSceneList` 调用 Binder 的同名方法。Binder 包装层继续转发；真正的 `VivoNotificationManagerServiceImpl` 检查 `isCallerSystemOrSystemUi()`，普通 UID 时直接返回，不抛异常。因此不能把反射调用正常返回当成获权。
2. `VivoSuperXNotificationManager.isValidSuperXNotification` 对完整模板检查包名与 scene 的允许映射；包名不在映射中会返回内部状态 `0x8a2`。
3. 同一方法确实保留了历史仅岛字段，但当 `islandNotify=true` 且存在 island Bundle 时，会先进入 `enforceHasIslandPermission`。普通包名需要 `com.vivo.notification.ISLAND_NOTI_SUPPORT`；本机权限定义为 `sourcePackage=android, prot=signature`。声明该权限不能让普通 debug 签名获权，历史路径不是通用绕过。
4. 正常路径的配置来自 `com.vivo.assistant.switchstateprovider` 和 `/data/bbkcore/vivo_superx_info_list.xml`。已定位读取链，但还没有检查 Provider 的完整访问控制或写入接口，不对它的可利用性下结论。
5. 该 ROM 在结束分支之前仍计算场景活动 key，所以构造器在 END 操作时保留 scene 或历史仅岛路由字段，避免结束通知落在 `NONE` 场景。

本机有睡眠/勿扰模式，通知记录显示 `mIntercept=true`；未更改这项用户设置。但 `SUPERX_VALUE=false` 和服务端权限判断已表明原子通知分类失败，不能将全部失败仅归因于视觉抑制。

当前结论：在已测普通包名和当前 ROM 下，补齐 payload 仍降级为普通通知。未完成 demo 包名对照、Provider 接口检查、root 路径或 OriginOS 7 验证；不能声称已经破解，也不能把当前两条路径失败扩大成所有可能路径均不可行。

## 已生成的 APK

| 本地产物（artifacts 目录） | 用途 | 包名 |
| --- | --- | --- |
| `Mutsumi-Atomic-Lab-debug.apk` | 首选独立诊断工具，可在界面比较四种路径 | `com.mutsumi.focus.atomiclab` |
| `Mutsumi-Atomic-Lab-demo-package-debug.apk` | 同源码、同 debug 签名，仅换用官方 demo 的测试包名 | `com.vivo.systemuitesttophone` |
| `Mutsumi-Focus-atomic-full-debug.apk` | 原计时器，修正 Icon 并补齐完整原子通知模板 | `com.mutsumi.focus.debug` |
| `Mutsumi-Focus-atomic-island-only-debug.apk` | 原计时器，开启历史仅岛字段 | `com.mutsumi.focus.debug` |

两个计时器候选包共用同一个 debug 包名，需要轮流安装；独立实验工具可以与原应用共存。各包的 SHA-256、实际包名和签名指纹记录在 `artifacts/atomic-island-local-manifest.json`。均为本地 debug 包，与正式发布签名不同。

## 验证记录（2026-10-11）

- 独立实验包及计时器候选包编译成功；默认诊断包和完整模板计时器的 lint 检查无错误。
- 原计时器的 14 项既有 Android 单元测试通过，失败/错误/跳过均为 0；这些测试不覆盖 vivo 的 ROM 权限或真实渲染。
- 四个 APK 均通过 `apksigner verify`，实际包名符合预期，debug 签名指纹一致。仅岛计时器生成的 BuildConfig 中 `VIVO_HISTORICAL_ISLAND_ONLY=true`。
- PowerShell 调试脚本语法和 Git 差异空白检查通过。
- 临时编译输出保存在 `E:/CodexBuild/408-Dashboard-atomic-island/`，未启动模拟器。真机当前验证范围和未完成项见上表。

输入附件 SHA-256：`d018ba090de717129cdb4c072c06c0e2273a25aac4341634a71c55aed735fb5f`。在线技术规范读取到的版本为 2，更新时间为 2025-09-03；快照保存在忽略目录中。

## 附件分析

输入为用户提供的 `D:/Desktop/superx_demo.rar`，参考内容保存在忽略目录 `.tmp/atomic-island-lab/reference/`；其中的说明只是待分析资料。

- demo 的 `applicationId` 为 `com.vivo.systemuitesttophone`，实际 Activity 类在 `com.example.testxnotification` 命名空间。`getPermissionGrant()` 却给 `TRAIN` 场景和 `com.example.testxnotification` 包名设置开关，而通知发送的是 `TAKEOUT`。这些并不一致，原样调用不能证明当前应用获权。
- `getPermissionGrant()` 反射调用 `NotificationManager.setSuperXInfosSceneList(List,List,List,List)`。这说明示例存在设置入口，但源码没有给出 framework/service 的调用者权限检查、签名要求或列表替换语义。实验包只检查接口可见性；先从真机 framework 和服务端实现核实这些边界。
- 原项目传给 `baseInfos.icon` 的值是资源整数，demo 和文档要求 `Icon`；原项目选 template 1，却缺少 `infos`、`shortInfos`、`island`、`capsule`。实验分支已补齐，并让计时应用与独立实验包共用同一构造器。
- 附件 PDF release1.5 第 7–9 页记载 `notification.superx.islandNotify=true` 的仅岛路径，此时 scene/template/卡片数据不参与取值。但当前公开技术规范没有这个字段。它是待测的历史路径，不能据此认定 OriginOS 7 仍支持，更不能把“不取 scene”推导为“不检查包名”。
- 当前 [vivo 技术规范](https://dev.vivo.com.cn/documentCenter/doc/896)仍给出错误码 32008（应用或场景未开通权限），并提供 `getSceneStatus(pkgName,sceneName)`；该接口读的是用户场景开关，不能单独作为厂商场景授权证明。

## 构建与产物

独立模块 `android/atomic-lab` 面向 Android 13+，没有网络或账号功能，仅生成 debug 变体；默认包名 `com.mutsumi.focus.atomiclab`。新版为 `0.2-local`，增加本包系统分类、系统处理回执和签名权限诊断；手机当前安装的最初测试版为 `0.1-local`，尚未在暂停期间更新。使用现有 Gradle/SDK/JDK：

```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-21'
$env:ANDROID_HOME = 'D:\Android\Sdk'
$env:GRADLE_USER_HOME = 'D:\GradleUserHome'
.\android\gradlew.bat -p android :atomic-lab:lintDebug :atomic-lab:assembleDebug
```

可通过 `-PatomicLabBuildDir=<绝对路径>` 放置临时构建输出。demo 包名对照使用 `-PatomicLabPackage=com.vivo.systemuitesttophone` 构建；安装时指定 `-Package com.vivo.systemuitesttophone -Apk artifacts\Mutsumi-Atomic-Lab-demo-package-debug.apk`。安装脚本在手机已存在官方 demo 包时会拒绝替换。包名比较并不模拟 vivo 签名。

正式计时器在该本地分支上默认仍发送完整模板及 `FOCUS_TIMER` 场景。若历史仅岛实验在真机有效，可用 `MUTSUMI_VIVO_ISLAND_ONLY=1` 构建计时器候选包；否则继续调查权限判断。不要把这个开关用于对外发布。

## 真机顺序

升级完成后，连接 USB 并在手机上允许调试。脚本默认仅接受一个已授权的真机；多个设备时指定 `-Serial`。

```powershell
.\scripts\atomic_island_lab.ps1 -Action Inspect
.\scripts\atomic_island_lab.ps1 -Action Install
.\scripts\atomic_island_lab.ps1 -Action Probe
.\scripts\atomic_island_lab.ps1 -Action Status
.\scripts\atomic_island_lab.ps1 -Action Plain
.\scripts\atomic_island_lab.ps1 -Action Full
.\scripts\atomic_island_lab.ps1 -Action Island
.\scripts\atomic_island_lab.ps1 -Action Android
.\scripts\atomic_island_lab.ps1 -Action Loop
.\scripts\atomic_island_lab.ps1 -Action End
.\scripts\atomic_island_lab.ps1 -Action Logs
```

通知未授权时，手机会显示授权入口，先完成授权再发实验通知。全模板默认 scene 为 `FOCUS_TIMER`；可用 `-Scene TAKEOUT` 对比附件示例的公开场景，画面仍显示真实的“专注实验”，这是本地诊断对照。

各模式使用固定通知 ID 9401–9404，互不复用。每 15 秒维护最多持续 3 分钟，之后结束实验通知；退出 Activity 时也结束。后台进程仍可能被系统回收，因此正式后台计时仍由原应用的前台服务负责。

岛回执只匹配本次实验的随机 callback token。工具还记录发往同包的 `android.app.action.SUPERX_STATE` 布尔回执，并通过 `getActiveNotifications()` 只读取本包通知的 `SUPERX_VALUE` 和 flags。接收到状态 1/3 可作为线索，但广播不能单独证明来源或视觉展示；需要同一通知的实际原子岛画面核对。`notify()` 成功、通知栏显示或 payload 包含字段，都不能代替这个核对。日志仅来自本实验包，保存在其私有目录 `files/atomic-lab.log`。

后续需要真机确定：历史仅岛字段是否保留；完整模板是否仍按包名/scene 拦截；官方 demo 包名是否有测试豁免；隐藏 setter 的服务端权限和修改范围。普通应用反射被拒绝时，先保留实际异常，再检查设备 framework/SystemUI；不把方法可见或调用返回当成绕过结果。
