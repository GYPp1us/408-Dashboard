# 本地原子岛实验

工作分支：`codex/atomic-island-local`。目标：用户自己的 iQOO 15 本机使用，不分发。在当前 OriginOS 6 上已通过 ADB shell 配置自有应用场景，并实际显示系统原生原子岛；OriginOS 7 尚未验证。

## 真机结果与权限判断

设备实际返回：型号 `V2505A`，Android 16/API 36，`OriginOS 6`，构建 `PD2505B_A_16.0.30.14.W10`。ADB 会话为 UID 2000（shell），`ro.build.type=user`；用户确认没有 root。

| 实验 | 当前证据 |
| --- | --- |
| 普通通知 | 用户已开启通知，普通通知可显示 |
| 完整模板 + `FOCUS_TIMER`，配置前 | `SUPERX_VALUE=false`，降级普通通知 |
| 完整模板 + `TAKEOUT` | 系统记录 `SUPERX_VALUE=false`，已清除原子通知数据块，保留普通通知 |
| 历史 `islandNotify=true` | 系统记录 `SUPERX_VALUE=false`，保留历史标记而剔除原子通知数据；主页没有岛 |
| Android 16 实时通知 | 用户手动试过后可见普通通知；`canPostPromotedNotifications=false`，系统无可解析的 APP_NOTIFICATION_PROMOTION_SETTINGS 入口。该项未完成独立的升级后验收 |
| 官方 demo 测试包名 | 已实测同源码、同 debug 签名的对照包；完整 `TAKEOUT` 和历史仅岛均返回 `SUPERX_STATE=false`、`SUPERX_VALUE=false`。仅改包名没有豁免；测试后保存私有实验日志并卸载这个临时对照包 |
| ADB 配置 `FOCUS_TIMER` 后 | 普通实验包 `getSceneStatus=true`、`SUPERX_STATE=true`、`SUPERX_VALUE=true`；主页截图实际显示“专注实验”和计时 |
| 撤销、重新启用 | 撤销后重新发送恢复 `SUPERX_VALUE=false`；启用后恢复 true 和原生岛。每次操作核对所有无关包名/scene 映射一致 |
| 维护 | CREATE 后 UPDATE 可将岛的文本更新到 `01:41`。实验 Activity 在缓存冻结时可能延迟，不能代替正式前台服务的后台验证 |
| 实验结束清理 | `0.4-local` 的 CREATE/UPDATE/END 后，本应用活动通知为零，岛正常消失；清理包含系统改写后的 `VIVO_SUPERX_TAG` |
| 原计时器 | 同签名本地包已更新原应用并保留登录。用户开启真实专注后 `SUPERX_VALUE=true`，`.FocusService` 的 `isForeground=true`；退到桌面后岛从 `00:00:45` 更新到 `00:02:18`，通知 `changedRecord` 从首次读取的 8 增到 17。用户真实专注保持运行 |

只读提取了本机 framework、services、vivo-framework、vivo-services、SystemUI 及系统助手 APK，原件位于 `E:/CodexBuild/408-Dashboard-atomic-island/firmware-PD2505B-A-16.0.30.14/`。反汇编、只含配置的快照和截图位于忽略目录 `.tmp/atomic-island-lab/device/`。

已核实的调用链：

1. `NotificationManager.setSuperXInfosSceneList` 调用 Binder 的同名方法。真正的 `VivoNotificationManagerServiceImpl` 检查 `isCallerSystemOrSystemUi()`，普通应用没有所需权限时直接返回，不抛异常。进一步追踪 `NotificationManagerService`，该判断除了系统/电话 UID，还接受持有 `android.permission.STATUS_BAR_SERVICE` 的调用者。本机 `com.android.shell` 已获这项权限，因此授权 ADB shell 能通过检查，无需 root。
2. `VivoSuperXNotificationManager.isValidSuperXNotification` 对完整模板检查包名与 scene 的允许映射；包名不在映射中会返回内部状态 `0x8a2`。
3. 同一方法确实保留了历史仅岛字段，但当 `islandNotify=true` 且存在 island Bundle 时，会先进入 `enforceHasIslandPermission`。普通包名需要 `com.vivo.notification.ISLAND_NOTI_SUPPORT`；本机权限定义为 `sourcePackage=android, prot=signature`。声明该权限不能让普通 debug 签名获权，历史路径不是通用绕过。
4. 正常路径的配置来自 `com.vivo.assistant.switchstateprovider` 和 `/data/bbkcore/vivo_superx_info_list.xml`。Provider exported，READ_DATA/WRITE_DATA 为 normal 权限，但其 `insert/update` 返回空/0，`call` 另有业务方法和调用包判断。本次没有调用或修改 Provider。
5. 该 ROM 在结束分支之前仍计算场景活动 key，所以 END 保留 scene 或历史仅岛路由字段。完整模板还须保留 `template=1`，否则缺省值 -2 会在进入 END 分支之前被拒绝；最终源码已修正并通过构建。`NotificationManager.notifyAsUser()` 把 SuperX 通知 tag 改为 `VIVO_SUPERX_TAG`，而 `cancel(id)` 仍取消 null tag。共有清理方法同时取消这两个 tag 的自有 ID，避免岛残留。

本机有睡眠/勿扰模式，未更改这项用户设置。配置后在该状态下仍能显示岛。

当前结论：完整模板配合 shell 侧本机场景配置可行，已用于原计时器。原子岛截图和系统分类均已确认；历史仅岛签名权限路径没有开通。重启、云配置刷新和 OriginOS 7 后的保持情况尚未测试。

## 本机启用和撤销

`scripts/vivo_atomic_local.ps1` 只支持已经反汇编核对的上述机型与固件。该固件 `INotificationManager.Stub` 的事务 209 为 `setSuperXInfosSceneList`，读取四个 StringArrayList；事务 210 为 `getSceneStatus(String,String,int)`。脚本校验机型/完整构建号，拒绝其他固件，避免升级后向错误方法发送 Parcel。

```powershell
.\scripts\vivo_atomic_local.ps1 -Action Inspect -Serial '<adb serial>'
.\scripts\vivo_atomic_local.ps1 -Action Enable -Serial '<adb serial>'
.\scripts\vivo_atomic_local.ps1 -Action Disable -Serial '<adb serial>'
```

启用只替换此前不存在的 `FOCUS_TIMER` 场景，包含实验工具、debug 计时器和原计时器三个自有包名。若这个场景中出现其他包名，脚本拒绝操作。每次写入保存配置区段快照，逐项核对其他场景映射没有变化，并读回各包场景状态。撤销移除这三个包名的映射，ROM 会保留一个空的禁用场景条目。若手机接在另一个 ADB 服务上，通过 `-Port` 指定；本次后半段使用 5038，未停止电脑已有的 ADB 服务。

服务实现会延迟 5 秒保存配置。没有通过重启验证持久性；助手或云端刷新可能覆盖本地配置。升级 OriginOS 7 后应重新检查 framework 的事务号、权限和渲染，再适配脚本。

## 已生成的 APK

| 本地产物（artifacts 目录） | 用途 | 包名 |
| --- | --- | --- |
| `Mutsumi-Atomic-Lab-debug.apk` | 首选独立诊断工具，可在界面比较四种路径 | `com.mutsumi.focus.atomiclab` |
| `Mutsumi-Atomic-Lab-demo-package-debug.apk` | 同源码、同 debug 签名，仅换用官方 demo 的测试包名 | `com.vivo.systemuitesttophone` |
| `Mutsumi-Focus-atomic-full-debug.apk` | 原计时器，修正 Icon 并补齐完整原子通知模板 | `com.mutsumi.focus.debug` |
| `Mutsumi-Focus-atomic-island-only-debug.apk` | 原计时器，开启历史仅岛字段 | `com.mutsumi.focus.debug` |
| `Mutsumi-Focus-atomic-local-v0.6.0.apk` | 完整模板、本地安装使用，与手机原应用签名一致 | `com.mutsumi.focus` |

两个 debug 计时器候选包共用一个包名，需要轮流安装；独立实验工具可以与原应用共存。`atomic-local` 包使用项目原有 release 签名，可更新手机原应用并保留应用数据，仅作为本地产物，不发布。其余包是 debug 签名；demo 包和历史仅岛包保留为旧路径对照。各包的 SHA-256、实际包名和签名指纹记录在 `artifacts/atomic-island-local-manifest.json`。

## 验证记录（2026-10-11）

- 独立实验包及计时器候选包编译成功；默认诊断包和完整模板计时器的 lint 检查无错误。
- 原计时器的 14 项既有 Android 单元测试通过，失败/错误/跳过均为 0；这些测试不覆盖 vivo 的 ROM 权限或真实渲染。
- 五个 APK 均通过 `apksigner verify`，实际包名符合预期。四个实验/debug 包的签名指纹一致；本机计时器包的签名与原安装一致。仅岛对照包的 BuildConfig 中 `VIVO_HISTORICAL_ISLAND_ONLY=true`。
- PowerShell 调试脚本语法和 Git 差异空白检查通过。
- 临时编译输出保存在 `E:/CodexBuild/408-Dashboard-atomic-island/`，未启动模拟器。真机当前验证范围和未完成项见上表。
- 新版实验工具、原应用 debug/release 构建通过；实验工具及原应用 lint 无错误，14 项单元测试继续通过。
- 完成 18 项公开版式实测，全部 `SUPERX_VALUE=true`，逐项查看画面。HTML 图集的图片均可解码，分类筛选数为 5/6/7，390px 手机宽度下无横向溢出。检查用的无头浏览器已关闭。

输入附件 SHA-256：`d018ba090de717129cdb4c072c06c0e2273a25aac4341634a71c55aed735fb5f`。在线技术规范读取到的版本为 2，更新时间为 2025-09-03；快照保存在忽略目录中。

## 附件分析

输入为用户提供的 `D:/Desktop/superx_demo.rar`，参考内容保存在忽略目录 `.tmp/atomic-island-lab/reference/`；其中的说明只是待分析资料。

- demo 的 `applicationId` 为 `com.vivo.systemuitesttophone`，实际 Activity 类在 `com.example.testxnotification` 命名空间。`getPermissionGrant()` 却给 `TRAIN` 场景和 `com.example.testxnotification` 包名设置开关，而通知发送的是 `TAKEOUT`。这些并不一致，原样调用不能证明当前应用获权。
- `getPermissionGrant()` 反射调用 `NotificationManager.setSuperXInfosSceneList(List,List,List,List)`。这说明示例存在设置入口，但源码没有给出 framework/service 的调用者权限检查、签名要求或列表替换语义。实验包只检查接口可见性；先从真机 framework 和服务端实现核实这些边界。
- 原项目传给 `baseInfos.icon` 的值是资源整数，demo 和文档要求 `Icon`；原项目选 template 1，却缺少 `infos`、`shortInfos`、`island`、`capsule`。实验分支已补齐，并让计时应用与独立实验包共用同一构造器。
- 附件 PDF release1.5 第 7–9 页记载 `notification.superx.islandNotify=true` 的仅岛路径，此时 scene/template/卡片数据不参与取值。但当前公开技术规范没有这个字段。它是待测的历史路径，不能据此认定 OriginOS 7 仍支持，更不能把“不取 scene”推导为“不检查包名”。
- 当前 [vivo 技术规范](https://dev.vivo.com.cn/documentCenter/doc/896)仍给出错误码 32008（应用或场景未开通权限），并提供 `getSceneStatus(pkgName,sceneName)`；该接口读的是用户场景开关，不能单独作为厂商场景授权证明。

## 构建与产物

独立模块 `android/atomic-lab` 面向 Android 13+，没有网络或账号功能，仅生成 debug 变体；默认包名 `com.mutsumi.focus.atomiclab`。手机已安装 `0.4-local`，增加公开版式选择器；最终本地产物为 `0.5-local`，补齐协议 END 的 template 字段并提供仅发 END 的对照按钮。USB 随后断开，0.5 更新和仅发 END 的真机验证尚待完成。`0.3-local` 补齐原子通知 tag 清理，`0.2-local` 新增本包系统分类、系统回执和签名权限诊断。demo 对照 APK 保留 `0.2-local`。使用现有 Gradle/SDK/JDK：

```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-21'
$env:ANDROID_HOME = 'D:\Android\Sdk'
$env:GRADLE_USER_HOME = 'D:\GradleUserHome'
.\android\gradlew.bat -p android :atomic-lab:lintDebug :atomic-lab:assembleDebug
```

可通过 `-PatomicLabBuildDir=<绝对路径>` 放置临时构建输出。demo 包名对照使用 `-PatomicLabPackage=com.vivo.systemuitesttophone` 构建；安装时指定 `-Package com.vivo.systemuitesttophone -Apk artifacts\Mutsumi-Atomic-Lab-demo-package-debug.apk`。安装脚本在手机已存在官方 demo 包时会拒绝替换。包名比较并不模拟 vivo 签名。

正式计时器在该本地分支上默认发送完整模板及 `FOCUS_TIMER` 场景，与已验证的 shell 配置配合。`MUTSUMI_VIVO_ISLAND_ONLY=1` 仅用于旧签名权限路径的对照，该路径在当前普通签名包下失败。

## 真机顺序

连接 USB 并在手机上允许调试。诊断脚本默认仅接受一个已授权的真机；多个设备时指定 `-Serial`。它本身不改变厂商场景配置；配置由上述本机启用脚本管理。

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

普通/完整/历史/Android 对照使用固定通知 ID 9401–9404；版式选择器用 9405，创建新样例会先结束其他实验通知。每 15 秒维护最多持续 3 分钟，之后结束实验通知；退出 Activity 时也结束。Activity 在后台可能被缓存冻结或回收，更新和结束会延迟；正式后台计时由原应用的前台服务负责。

岛回执只匹配本次实验的随机 callback token。工具还记录发往同包的 `android.app.action.SUPERX_STATE` 布尔回执，并通过 `getActiveNotifications()` 只读取本包通知的 `SUPERX_VALUE` 和 flags。接收到状态 1/3 可作为线索，但广播不能单独证明来源或视觉展示；需要同一通知的实际原子岛画面核对。`notify()` 成功、通知栏显示或 payload 包含字段，都不能代替这个核对。日志仅来自本实验包，保存在其私有目录 `files/atomic-lab.log`。

## 公开版式实测

共 18 项样例（基础卡片主模板和“无辅助区”是重叠对照），全部被系统接受，实际渲染与模板名称对应：

| 组 | 样例 | 数量 |
| --- | --- | --- |
| 通知卡片主模板 | 强调信息、节点进度、左右对称、基础信息、导航 | 5 |
| 原子岛右侧 | 律动、进度环、加载、文字+图标、图标+文字、胶囊文字 | 6 |
| 基础卡片辅助区 | 无、文字、胶囊、图片、多图片、进度、加载 | 7 |

原子岛左侧公开参数只有图标+文本，本次固定使用这一版式。旧 PDF 的岛大卡枚举提到 6“自定义”，但当前公开通知主模板只提供 1–5 及对应参数；本次没有把缺少完整协议的内部/自定义枚举当成公开版式进行伪造测试。

实机图集：`artifacts/atomic-island-layout-gallery.html`，离线自包含，可筛选三组；律动和加载条目由连续实机截屏组成 GIF。结构化分类记录为 `artifacts/atomic-island-layout-results.json`；原始截图及每项自有日志在忽略目录 `.tmp/atomic-island-lab/device/layouts/`。这些内容未提交或发布到远端。

在实验工具选择器中可自行逐项发送；自动截图脚本使用独占锁，每组结束后核对活动实验通知为零：

```powershell
.\scripts\atomic_island_lab.ps1 -Action Layout -Layout r2 -Serial '<adb serial>' -Port 5038
python .\scripts\vivo_layout_sweep.py --serial '<adb serial>' --port 5038 --group cards
python .\scripts\vivo_layout_sweep.py --serial '<adb serial>' --port 5038 --group islands
python .\scripts\vivo_layout_sweep.py --serial '<adb serial>' --port 5038 --group base
```

使用 Python 时需 Pillow。测试期间保持实验界面，避免人工操作与截图流程重叠。通知文本、进度和导航均是明确标记的本地样例。锁屏、云刷新、重启及 OriginOS 7 的表现仍需后续真机检查。
