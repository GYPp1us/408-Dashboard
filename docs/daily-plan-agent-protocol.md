# Daily Plan v1 · Agent 接入

APP 的“复制接入 Prompt”会将下方占位链接替换为当前账户的真实鉴权链接。

请按 daily-plan.v1 协议接入 Mutsumi Focus，每日计划以本端数据口径为准。
1. GET https://platform.arcol.site/api/daily-plan-reporter/<key>/today 读取账户时区下的今日 tasks、completed/total、focus_seconds、completion_records，以及 subjects/focus_items 目录。可选 ?date=YYYY-MM-DD 读取指定计划日。
2. POST https://platform.arcol.site/api/daily-plan-reporter/<key>/frame，Content-Type: application/json。最简 JSON：{"tasks":[{"title":"完成一套数学模拟"}]}。
完整示例：{"source":"my_agent","date":"2026-10-24","tasks":[{"external_id":"math-paper-01","title":"完成一套数学模拟","note":"先限时，再订正","target_minutes":120,"subject_id":1,"focus_item_id":2}]}。
source 可省略，默认 agent，建议每个系统固定一个英文标识。date 可省略，使用服务端账户今日。external_id 可省略，按规范化任务名生成；需要改名时应固定 external_id。相同来源、日期及外部 ID 幂等更新，省略项不会删除旧任务。
subject_id/focus_item_id 使用 GET 返回的本账户目录 ID，可省略；有项目时科目需匹配。target_minutes 为 0–1440 整数，可省略；note 可省略。archived=true 移出任务但保留历史；省略 completed 不会重置完成状态。
3. GET https://platform.arcol.site/api/daily-plan-reporter/<key>/today 可随时查看用户在 APP 中归类的真实专注记录与完成状态。一个任务可关联多段专注，focus_seconds 自动扣除暂停，重复保存不重复计时。
确需主动更正完成状态时，POST https://platform.arcol.site/api/daily-plan-reporter/<key>/complete，JSON {"task_id":目录中的数字ID,"completed":true,"expected_revision":读取到的revision}。false 可撤销完成；409 daily_task_changed 时重新读取，不盲目覆盖。
4. 准备一个公网 HTTPS JSON 接收接口，在 APP 每日计划接入设置中填写地址，以及可选的双方约定鉴权密钥。结算后本端主动 POST，不要求接收方轮询等待。
推送示例：{"protocol":"daily-plan.v1","event":"daily_settlement.completed","event_id":"稳定事件ID","date":"2026-10-24","settled_at":"ISO时间","timezone":"Asia/Shanghai","tasks":{"date":"2026-10-24","total":2,"completed":1,"focus_seconds":7200,"tasks":[...],"completion_records":[...]}}。
请求头 Idempotency-Key 与 event_id 相同；配置密钥时带 Authorization: Bearer <双方约定密钥>。校验并持久保存后返回任意 2xx，勿依赖响应正文。
推送至少一次，可能重试；同一 event_id 的结算快照保持不变，接收端必须按 event_id 去重。不得因重复推送重复累加时长或完成次数。结算后的任务修改可通过今日接口读取，不会改写已结算快照。
用户取消已推送或结果不确定的结算时，还会收到 {"protocol":"daily-plan.v1","event":"daily_settlement.cancelled","event_id":"撤销事件ID","retracts_event_id":"原结算事件ID","date":"YYYY-MM-DD","cancelled_at":"ISO时间"}，请按 retracts_event_id 撤销对应快照。新的重新结算使用新事件 ID。
5. key 长期有效，只有在 APP 手动更换后旧链接失效；与专注上报、打卡 key 独立。链接含密钥，按密码保护，不写公开仓库或日志。401 表示 key 无效；404 表示任务/项目不属于本账户；409 表示状态冲突。不要用模拟数据回报真实任务已完成。
