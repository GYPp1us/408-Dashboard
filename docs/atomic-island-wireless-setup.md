# 本机无线调试启用原子岛

本地分支 `codex/atomic-island-local` 的 `0.6.1-local` 增加应用内引导。它直接从手机应用连接同一手机的 adbd，不依赖电脑 ADB server 或安装后的 USB 连接。用户仍须在系统中手动开启无线调试并输入配对码。

入口：竖屏计时器顶部常驻的 **原子岛与提醒设置** → **启用 OriginOS 原子岛 · 本机引导**。已有权限全开也保留入口。

## 操作

1. 连接 Wi-Fi，在开发者选项中开启无线调试；将应用引导和系统设置分屏或小窗并排显示。
2. 系统选择“使用配对码配对设备”。保持弹窗打开，在应用中输入**配对端口**与六位配对码，点“完成本机配对”。
3. 回到无线调试主页，输入主页“IP 地址与端口”中的**连接端口**，点“连接并启用原子岛”。两个端口不同，重新开启调试后可能变化。
4. 完成授权回读后，可关闭无线调试，回到正常专注计时。

撤销只移除当前 APK 包名的 `FOCUS_TIMER` 映射，保留其他自有包和无关场景。忘记系统中的 `Mutsumi-Focus-local` 配对设备会撤销调试授权，不会撤销原子岛映射。

## 实现与边界

- `AtomicIslandSetupActivity` 不导出，也不向网页 JS 暴露接口。所有连接固定为 IPv4 loopback `127.0.0.1`，没有自定义远程地址或通用终端。
- 使用 Kadb 1.3.0 与 Android 无线调试的 TLS/配对码流程。选择这一版是为了兼容现有 AGP 内置 Kotlin 编译器；配对密码不写入文件、不保存界面状态、不记日志。
- RSA 私钥与证书保存在应用 `noBackupFilesDir` 的私有原子文件中；配对后启动新进程仍使用同一凭据。场景写入前后保存过滤后的配置区段，不读取其他应用通知内容。
- Kadb 1.3 的配对 socket 缺少超时和取消接口，因此增加只转发加密字节的单次 loopback relay。连接有 4 秒建立超时、20 秒读超时、35 秒整体截止时间；成功、失败、取消或页面销毁都关闭连接与工作线程。它不终结 TLS 或替代配对认证。
- 当前写入适配范围严格限定为 `V2505A / PD2505B_A_16.0.30.14.W10`。连接后再核对机型、完整构建号及 shell UID 2000，使用已反汇编验证的 Binder 209/210，并回读结果。升级 OriginOS 7 后禁用写入，待重新核实事务号和服务逻辑。
- 注册当前包只接受 `com.mutsumi.focus` 和 `.debug`；遇到 `FOCUS_TIMER` 中的外部包名、异常/重复配置、Binder 异常或回读不符时停止。成功不能单独证明真实渲染，仍须观察 native 原子岛。
- 该修改不取得 root。日常计时更新仍由应用已有的前台服务和通知 payload 完成；无线调试只用于启用/撤销系统场景配置。
- Kadb 是 Apache-2.0；其配对依赖 **SPAKE2 Java 1.0.5 是 GPL-3.0-or-later**，不能把整个依赖链标成 Apache。本机分支保留许可证、版本及源代码链接，应用内提供“开源许可”。未分发或上架。

## 当前验证

新增注册边界测试 8 项、loopback 字节转发/超时清理测试 2 项，与既有 14 项一起共 24 项通过。Android Debug lint 无错误，签名 Release 构建与签名检查通过。

2026-10-11，`0.6.1-local / versionCode 12` 已更新安装到用户的 iQOO 15，原应用签名一致，真机查看了引导页面。用户回复确认“本机配对并启用成功”。随后电脑仍能通过 USB ADB 读取手机，因此单独请求拔线后再次操作并确认第三步结果；完全离线操作的确认仍待补充。此前原子岛真实渲染已由前一阶段真机实验验证，不能用页面顶部已有授权状态替代此次本机连接/注册结果。

最终 APK SHA-256：`730f33218905f9390d6e17931eccb9bba5de0c25a6c3ec7d41af12cc7228e710`。构建/缓存放在 E 盘，交付 APK 放在当前任务的 C 盘可视化目录 `atomic-island-wireless/`；未启动模拟器。

## 参考

- [Android 无线调试](https://developer.android.com/tools/adb#wireless-android11)
- [Kadb 1.3.0](https://github.com/flyfishxu/Kadb/tree/1.3.0)
- [LADB 的同机分屏配对说明](https://github.com/tytydraco/LADB)
- [既有真机实验与 18 种版式](atomic-island-local-lab.md)

没有找到官方公开的 OriginOS AVD 镜像。完整手机固件不能直接作为 AVD 镜像使用；自定义 AVD 需要对应虚拟硬件构建。此前从用户手机提取的 framework、服务及 SystemUI 用于静态分析；真实 vivo 授权及渲染仍以真机验证为准。[Android AVD 构建说明](https://source.android.com/docs/setup/test/avd)
