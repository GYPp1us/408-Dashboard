# 每日打卡与外部上报

在专注入口的打卡标签创建任务。每项每天完成一次，时间段和地点条件独立可选，两者都设置时取交集。条件使用账户时区及服务器接收时间；跨午夜时段在午夜后的完成归入新的账户日。位置需要 latitude、longitude 和 accuracy（米），精度不能大于配置半径，距离不能超过半径。重复已完成帧返回原记录，包括当天之后离开时间段的重复帧。

登录后在设置的“外部打卡上报”复制链接或接入提示。GET catalog_url 返回当前账户 checkin_items，POST report_url 提交：

```json
{"source":"study_app","state":"checkin","checkin_item_id":1,"latitude":30.0,"longitude":120.0,"accuracy":10}
```

ID 从目录获取。source 为 1～64 位字母、数字、点、下划线或短横线；没有地点条件时可省略位置三字段。state=idle 表示不触发新打卡，不撤销完成记录。可按专注上报相同的周期发送快照，也可以只在打卡触发时发送；打卡没有失联自动结束或自动撤销。

key 长期有效、按账户隔离，与专注上报 key 独立；仅手动更换打卡 key 后旧链接立即失效。链接等同账户打卡凭据，采用 HTTPS。服务重启、版本升级或应用 secret 轮换不会更换 key。

成功返回 ok、state、changed、record_id、date、accepted_at。changed=false 表示当天同一项已完成；并发或重复上报只产生一个记录。401 为无效 key；404 为项目不属于账户或已移出；409 包括时间段不满足、地点不满足或精度不足；400 为字段格式不正确。

登录界面使用 /api/checkins（GET 目录、POST 新建）、/api/checkins/<id>（PUT 编辑、DELETE 移出）、/api/checkins/frame（POST 触发）和 /api/checkins/history?date=YYYY-MM-DD。移出采用存档，历史完成保留。迁移导出追加 checkin_rules 与 checkin_records，保留原格式版本，不导出上报 key。

没有任务的日子在热度图显示未配置。有任务时完成度为已完成项数/当日生效任务数；已完成但当天移出的任务仍保留在当日分子和分母。新任务不会倒填历史日期的目标数。
