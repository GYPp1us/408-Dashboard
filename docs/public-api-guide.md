# Mutsumi Focus 公网 API 接入指南

生产地址：[https://platform.arcol.site](https://platform.arcol.site/)。**只读展示用访客 Cookie；外部软件或 Agent 上报用对应的专用 key。** 上报请求使用 `Content-Type: application/json`，日期使用 `YYYY-MM-DD`；未指定的计划日期按账户时区计算。

## 1. 无密码读取公开看板

先访问 [`/guest`](https://platform.arcol.site/guest) 获取访客 Cookie，默认查看站点所有者。查看指定账户时改用 `/<username>/guest`。后续请求复用同一个 Cookie；用独立会话，避免覆盖现有登录状态。直接访问下列 API 不带 Cookie 会返回 `401`。

```sh
BASE=https://platform.arcol.site
curl -fsS -c guest.cookies "$BASE/guest" -o /dev/null
curl -fsS -b guest.cookies "$BASE/api/focus-kline/live"
```

| GET 路径 | 用途 |
| --- | --- |
| `/api/dashboard` | 看板汇总：当前与累计专注、热度图、模考成绩、已结算摘要 |
| `/api/focus` | 当前专注及近期记录 |
| `/api/focus/interval?date=YYYY-MM-DD&hour=8` | 热度图某个两小时格的专注明细；`hour` 用账户时区的偶数整点 |
| `/api/focus/items/{id}/summary` | 某个专注事项的累计时间及近期记录；ID 取自看板的 `focus_items` |
| `/api/focus-kline/live` | 最新指数与当日分时线 |
| `/api/focus-kline`，可选 `?date=YYYY-MM-DD` | 历史日线；`date` 选择需要随附的分时走势 |
| `/api/daily-settlement/report`，可选 `?date=YYYY-MM-DD` | 已结算报告；该日未结算返回 `404` |

访客可读已有公开统计，包括打卡完成度。每日计划任务及其完成明细保持私有；打卡规则和独立的打卡历史接口需要账户权限。

## 2. 外部上报与读取待办

在 APP 或网页设置的「外部专注上报」「外部打卡上报」复制接入提示。每日计划在 APP「每日计划 → 接入与推送设置」复制接入 Prompt。三种 key 独立、长期有效，直接放在 URL 路径中，无需登录 Cookie；手动轮换后旧链接失效。把完整链接当作密码保管，勿写进仓库或日志。

| 场景 | URL 前缀 | 用法 |
| --- | --- | --- |
| 专注上报 | `/api/focus-reporter/{key}` | `GET /catalog` 读取 `subjects`、`focus_items`；`POST /frame` 更新状态 |
| 打卡上报 | `/api/checkin-reporter/{key}` | `GET /catalog` 读取 `checkin_items`；`POST /frame` 提交打卡 |
| 每日计划 | `/api/daily-plan-reporter/{key}` | `GET /today` 读今日待办与完成状态，可带 `?date=YYYY-MM-DD`；`POST /frame` 上报计划，`POST /complete` 更正完成状态 |

以下是请求体示例。数字 ID 以对应 GET 接口的实际返回为准：

| POST 操作 | JSON 示例与行为 |
| --- | --- |
| 专注 `/frame` | `{"source":"study_app","state":"focus","subject_id":1,"focus_item_id":2}`。同一来源与事项每 10–30 秒续发一次；结束时发送 `{"source":"study_app","state":"idle"}`。失联 45 秒自动结束，按服务端收到帧的时间计时。 |
| 打卡 `/frame` | `{"source":"study_app","state":"checkin","checkin_item_id":1}`。地点打卡增加 `latitude`、`longitude`、`accuracy`（米）；每项每天只计一次，重复成功返回 `changed:false`。 |
| 每日计划 `/frame` | `{"source":"my_agent","tasks":[{"external_id":"math-01","title":"完成一套数学模拟"}]}`。同一账户、日期、`source` 和 `external_id` 重发会更新同一任务；没传的任务保留。 |
| 每日计划 `/complete` | `{"task_id":1,"completed":true,"expected_revision":3}`。`task_id` 和 `revision` 来自 `/today`；`completed:false` 撤销完成。版本冲突时重新读取再决定是否重试。 |

常见错误：`400` 参数有误；`401` 缺少或使用了无效凭据；`403` 访客没有该权限；`404` 目标不存在或不属于该账户；`409` 状态冲突或打卡条件不满足。处理时同时读 JSON 的 `error` 字段。

## 3. 接收结算推送

在 APP 的计划接入设置中填入你自己的公网 HTTPS 接收地址，可配置接收端 Bearer 密钥。每日结算后，Mutsumi Focus 向该地址 `POST` `daily-plan.v1` JSON，`event: "daily_settlement.completed"` 的 `tasks` 是冻结的任务完成快照。接收端按 `event_id`（也在 `Idempotency-Key` 请求头里）去重，落库后返回 `2xx`；失败可能重试。收到 `daily_settlement.cancelled` 时，用 `retracts_event_id` 撤销对应快照。

普通 Agent 不需要 APP 的登录 Cookie，也不用调用前台心跳、内部结算或设置接口。数据迁移另走 `GET /api/migration/export`，用站点管理员生成的 `X-Migration-Code`（15 分钟有效，成功调用后失效）。详细字段见 [每日计划协议](daily-plan-agent-protocol.md) 和 [打卡协议](checkin-reporter.md)。

提醒验证题库通过 `GET` / `PUT /api/reminder-questions/bank` 维护，使用独立的 Bearer 密钥，支持编辑、替换和清空整个题库。获取密钥和请求格式见 [提醒题库接入](reminder-question-bank.md)。
