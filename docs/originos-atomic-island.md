# OriginOS 原子岛：无认证实现边界

## 结论

无认证时不是“全都不可用”。vivo 文档的本地创建、更新、结束路径使用 Android `NotificationManager` 和通知 `extras`，本身不需要 VPush token；应用可以照常调用。真正进入原子岛仍需要系统认可当前包名对应的场景权限。未认证包名使用自定义 `FOCUS_TIMER` 场景时，应把“系统降级为普通通知”视为正常首发结果，而不是承诺必定上岛。

代码只在 vivo/iQOO 设备附加以下文档字段：

- `notification.superx.operation`：创建 `0`、更新 `1`、结束 `2`；
- `notification.superx.showNotify=true`：无法上岛时保留普通通知；
- `notification.superx.template=1`；
- `notification.superx.clickResp`：返回应用的不可变 `PendingIntent`；
- `notification.superx.scene`：默认 `FOCUS_TIMER`，可在获批后由构建变量替换；
- `notification.superx.baseInfos`：图标、标题、正文。

没有伪装成健康打卡、打车、外卖、航班等已公开场景。伪造场景既不可靠，也可能造成审核和系统策略风险。

参考：[vivo 原子通知开发文档](https://dev.vivo.com.cn/documentCenter/doc/896#s-9xftohi5)、[Android Live Update 文档](https://developer.android.com/develop/ui/views/notifications/live-update)。

## 首发降级矩阵

| 层级 | 无 vivo 认证 | 需要用户授权 | 备注 |
|---|---:|---:|---|
| WebView 与网页同步 | 可用 | 登录 | 原站点 Cookie，同源 API |
| 前台计时与 15 秒心跳 | 可用 | 通知建议开启 | 避免网页退后台后 30 秒超时 |
| 普通持续通知及暂停/结束操作 | 可用 | Android 13+ 通知权限 | Android 8+ |
| Android 16 Live Update | 可尝试 | 系统“推广实时通知”开关 | 系统仍会检查通知特征 |
| vivo 原子通知本地调用 | 可调用 | 通知权限 | 系统可能因 scene 未授权而降级 |
| OriginOS 原子岛形态 | 不保证 | vivo 场景/包名权限 | 这是未认证首发的硬边界 |
| 暂停/结束全屏半透明提醒 | 可用 | 无障碍覆盖层或悬浮窗 | 未授权时退化为高优先级通知 |
| 后台保活 | 可用但受系统调度影响 | 电池白名单、自启动 | 前台服务 + 局部唤醒锁 |

## 真机验收清单

建议至少使用一台当前主力 OriginOS 设备和一台 Android 16 设备：

1. 全新安装，确认权限引导逐项打开通知、无障碍提醒层、显示在上层、电池不限制和 vivo 自启动。
2. 登录后开始专注，锁屏并退后台 2 分钟；网页会话应保持 active，持续通知计时应继续。
3. 在通知上执行暂停、继续和结束；重新打开网页后状态应一致。
4. 暂停满 5 分钟，确认出现半透明/毛玻璃遮罩；轻点其他区域回应用，右滑红色“继续摸鱼”后再延迟 5 分钟。
5. 结束后依次验证 15、30、60 分钟提醒；完成 60 分钟提醒后前台服务应退出。
6. 进入“休息”或正常专注时，确认没有超时提醒。
7. 在通知历史或系统日志中确认未获场景权限时普通通知仍存在；记录 OriginOS 版本、机型、是否真正上岛。
8. 重启设备后验证未完成的暂停/结束提醒状态可恢复。

原子岛是否出现只能以目标真机结果为准。Android 模拟器可验证服务、界面和时序，不能代替 vivo 的场景权限判定。
