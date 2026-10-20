# 原子通知的系统计时探测（2026-10-20）

## 结论与范围

已在用户连接的 iQOO 15 上确认：普通应用可以在现有获准的原子通知场景中，发送一次 JSON 计时描述，由系统自行推进原子岛及强调模板的计时文字，无需每秒重新投递通知。本次实验没有使用仅岛签名权限、修改场景映射、接入生产账户或更改正式应用代码。

系统秒表与当前正式应用的差异包含两个独立部分：

1. 秒表发送计时基准和格式，系统渲染器走秒；正式应用发送当前时间字符串，每秒 UPDATE 整条原子通知。
2. 秒表设置 `notification.superx.displays=273`（`0x111`，通知、锁屏、状态栏），不包含桌面组件位；正式应用未显式设置此字段，采用模板的默认触点范围。

因此，系统秒表本次并未使用另一条“仅岛”通道：其 `notification.superx.islandNotify=false`，`scene=TIMER`，主模板为 4。减少通知投递与限制显示触点应分别设计，不能混为同一个开关。`showNotify=false` 只影响失败后的普通通知兜底。

## 设备和证据

- 机型：`V2505A`（iQOO 15）。
- 构建：`PD2505B_A_17.1.9.0.W10`；Android 17 / API 37；`ro.vivo.os.version=17.0`。
- 系统时钟：`com.android.BBKClock`，8.0.5.6（8000506）。
- SystemUI：17.0.6.50（170060050）。
- 本次普通实验包回读 SuperX 协议版本为 8，`getSceneStatus=true`，`SUPERX_VALUE=true`，仅岛权限 protectionLevel=2 且未获权。
- 旧探测固件为 `PD2505B_A_16.0.30.14.W10`，不是本次设备固件。本次没有调用旧脚本的 Binder 写入或扩大适配表。

只保留了系统时钟、正式应用和实验包的相关活动通知记录，未保存其他应用通知正文。原始 APK、局部截图、采样和实验源文件在忽略目录 `.tmp/atomic-timer-probe-20261020/`，不随文档提交原始系统二进制或设备私有日志。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| BBKClock.apk | 14415124 | `37f849a7f0ccf73b2d1b2063c28a3835614a38caf4af56af44ec811f915b6544` |
| SystemUI.apk | 59217269 | `8611aa9486246d311f843859de3822db09ed0d67cfa9b05743e315821e92af92` |
| SystemUIPlugin.apk | 126841415 | `f986370823d8d3053aa84af4b11106f60b9e2303bef1c3c5ad3fd3cd52fbeeaf` |
| framework.jar | 55068711 | `4f939caeb45c2a23cdc835f0c434b268da78201ff9b4a0425fee236a04f7604b` |
| vivo-framework.jar | 8955385 | `a6180bdec3f6f8ba52c75124bd62a64dc2479aaf8cacfc77468e772b9e3bb485` |

## 计时协议

系统时钟的 `baseInfos.title`、`shortInfos.coreInfoShort` 中实际携带以下结构（`base` 是设备运行时间轴上的毫秒基准，不是 Unix 时间）：

```json
{
  "base": 816170981,
  "contentFormat": "%s",
  "countDown": false,
  "elapsedFormatHMS": "%1$02d:%2$02d:%3$02d",
  "elapsedFormatMS": "%1$02d:%2$02d",
  "elapsedFormatS": "%1$d",
  "minUnit": "M",
  "started": true
}
```

在 `com.vivo.systemuiplugin` 中找到了实现类：

- `com.vivo.systemuiplugin.superx.common.service.ui.TimerFormat`
- `com.vivo.systemuiplugin.superx.common.service.ui.SuperXChronometer`

`SuperXChronometer.setContent(CharSequence)` 检测并反序列化 `TimerFormat`，通过 `setTimerWithFormat` 设置方向、基准、格式和运行状态。`updateText` 使用 `SystemClock.elapsedRealtime()` 与 `base` 的差计算时间；系统视图自行调度约 1000ms 的刷新，并根据可见性、屏幕等状态管理刷新。代码没有在这个文字刷新路径中调用应用的 NotificationManager。

这与 `Notification.Builder.setUsesChronometer(true)` 不是同一处配置：实验包未启用标准 Android chronometer 或 ProgressStyle，只向原子通知文本字段传入 JSON。此前关闭标准 chronometer 叠加，不能等同于已使用此厂商计时能力。

## 定向实验

实验使用 `com.mutsumi.focus.atomiclab`，沿用它原有的 `FOCUS_TIMER` 场景授权，以普通应用 UID 调用 NotificationManager。没有新增授权写入、服务、网络请求或循环发送通知的任务。构建使用临时 source-set 覆盖，仓库中正式 Android 源码未改动。

| 实验 | 观察 | 限定 |
| --- | --- | --- |
| 系统秒表 | 12 次通知采样的 `mUpdateTimeMs` 均为 `1792507512506`；岛截图由 03:12 变为 03:17 | 证明该段时间不靠重新投递通知走秒 |
| 普通实验包，基础模板、岛计时 | 单次 notify；12 次采样的更新时间均为 `1792508049742`；岛由 02:08 变为 02:14 | 已确认普通场景可以使用，不依赖仅岛权限 |
| 普通实验包，强调模板、右岛计时 | 收起态右侧正常走秒；强调模板 `infos.coreInfo` 也接受计时 JSON | 不要求把暂停文字和时间左右互换 |
| 强调模板主动展开 | 单次发送后，展开核心信息从 00:42 变为 00:44；最终通知更新时间仍为 `1792508791982` | 展开态文字可自行走秒，15 秒保持未通过验收 |
| 普通实验包，倒计时 | 收起态由 01:27 变为 01:21；两次采样更新时间同为 `1792508901764` | 只验证正常倒计时，没有把到零行为视为已验证 |

主动展开的截图约 4.4 秒时仍展开，约 10.7 秒时已经收起。当时正式应用的打卡倒计时也在逐秒投递通知，存在多活动竞争，未隔离“默认出卡时长”和“其他通知抢占”。不能据此保证改用系统计时就能保持 15 秒，也不能据此断言所有场景都不能保持。生产实现仍须独立验证一次展开、期间零计时 UPDATE、一次到期收起和手动收起不重弹。

本次没有将实验包的显示范围扩大到桌面组件，因而没有对“保留桌面卡片且其内部自行走秒”的实际渲染作保证。系统秒表排除桌面组件这一事实与系统自行计时能力分别成立。

## 接入时的边界

- 真实开始、暂停、继续、休息、结束、提醒轮次和主题变化仍须立即投递；只消除纯秒数变化造成的通知 UPDATE。
- 应先用校准后的业务时间计算已用／剩余时长，再映射到本机 `elapsedRealtime`。不可把服务端 Unix 时间直接填进 `base`，也不可跨手机重启复用旧基准。
- 本次未验证暂停后冻结的参数持久化、重启恢复、到零／超时行为；不能把实验脚本中未使用的静止模式当成正式协议。
- 系统格式化器按小时、分钟、秒分支处理。`minUnit=M` 不代表超过一小时仍显示“总分钟:秒”。现有小胶囊不带小时的要求需要额外适配；不能直接照抄系统的 HMS 格式。
- 系统渲染器能从 SpannableString 提取 ForegroundColorSpan 和 StyleSpan；现有 AbsoluteSizeSpan、TypefaceSpan 的呈现不能直接推定保持，需要真实版式验收。
- 进度值／进度环不是计时文字本身。本次没有证明它们能根据同一基准自动推进，需要单独确定刷新粒度。
- 15 秒展开与计时文本是两个独立问题；不得用 `showTime` 的岛生存时长替代已验证的卡片保持接口。
- 不支持该能力或尚未验证的 ROM 继续保留现有兼容路径。系统计时减少应用通知投递，但不代表零耗电；本次没有做耗电量化。

## 清理

实验结束后移除独立实验包的 9480 号通知，恢复实验前备份的 0.4-local APK，并核对恢复包哈希与通知清理结果。用户自行启动的系统秒表保留运行，正式应用的业务状态及生产服务端不改动。没有启动模拟器。

相关材料：[vivo doc896](https://dev.vivo.com.cn/documentCenter/doc/896)、[早期固件探测](atomic-island-local-lab.md)、[现有刷新节奏审计](frontend-timing-audit-v0.7.6.md)。


## 0.8.0-rc1 接入

在已验证的 `V2505A / PD2505B_A_17.1.9.0.W10` 组合上启用系统文字计时，其他机型或固件沿用原兼容刷新。小胶囊继续采用总分钟 `m:ss`，通过十分钟分段基准适配小时格式限制；每逢分段边界重新提交一次。大时间采用 `h小时m分钟` 或 `m分钟s秒`。定时专注进度按整数百分比更新，真实状态、主题、提醒轮次及明显计时更正仍立即提交。

该路径沿用系统时钟的 `displays=0x111`，显示于通知、锁屏、岛，排除桌面原子通知组件。普通走秒不再逐秒重新投递通知；未启用标准 Android chronometer 叠加。未扩大场景授权，也未加入新的设备配置写入。

保持原有一次展开、不重复弹出、到 15 秒发送一次收起的策略。保持期间不为装饰性进度或格式变化重新投递，但系统文字自行计时。当前设备没有再次连接，正式包 15 秒保持、手动收起及跨十分钟边界的实际视觉效果仍需验收，不能把先前实验当作该正式包已完成真机验证。
