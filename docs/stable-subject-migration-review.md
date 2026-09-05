# 科目—专注事项层级迁移：生产审查清单

状态：**尚未获准在生产执行迁移。** 在本文件的预检、备份演练和人工审查完成前，不得重启 `408-dashboard.service`，也不得对生产 SQLite 执行迁移脚本。

## 迁移后的数据模型

原来的 `user_focus_modes.subject` 是单层显示文本，例如 `408二轮`。新模型将它拆为两个稳定层级：

- `user_subjects`：成绩录入使用的科目（如 `408`），账户内名称归一化后唯一，并保存当前目标分；
- `user_focus_items`：专注时使用的事项（如 `二轮`），从属于一个科目，科目内名称归一化后唯一，并保存用户自定义排序；
- `focus_sessions.subject_id` 与 `focus_sessions.focus_item_id`：同时保留科目和事项的稳定关联；
- `scores.subject_id`、`plans.subject_id`：只关联科目；
- 默认保留所有历史表原有的 `subject` 文本作为不可改写快照；只有负责人逐条批准的未关联记录才可由独立清理步骤删除。

旧事项只会在以下规则明确时转换：名称必须以 `一轮`、`二轮` 或 `模拟` 结尾。例如 `408二轮` 会变成 `408` 下的 `二轮`。不能按该规则拆分的名称不会猜测归属。

历史文本的关联规则同样保守：

- `408二轮` 这类完整旧事项名：关联到 `408` 和对应的 `二轮` 事项；
- `408` 这类科目名：仅关联到 `408`；
- 没有匹配项的文本：原样保留，新的稳定 ID 保持 `NULL`。

## 已落实的安全边界

- 常规应用启动遇到任何预检风险（包括 review）都会在 DDL 前停止；服务启动不能绕过人工审查。
- `--approve-review` 只能在单进程迁移命令中接受已审阅的非阻断项，绝不能绕过 blocking 项。
- 旧事项拆分、重复的“科目 + 事项”组合、无效目标分、孤儿账户、跨账户稳定 ID 关联和已有外键违规全部为 blocking。
- 删除科目或事项只会将历史稳定 ID 置空；常规迁移不会删除或重写历史显示文本。
- 新专注事项的顺序是每个账户的一份连续排序列表；迁移沿用旧事项 ID 的顺序。
- 预检脚本以只读 URI 和 `PRAGMA query_only` 打开数据库，且不会调用 `init_db`。

## 必须审查的风险

| 风险 | 预检行为 | 需要的人工决定 |
| --- | --- | --- |
| 旧事项不能拆为“科目 + 一轮/二轮/模拟” | **阻断** | 指定每条旧事项的科目和事项，或先在副本中修正。 |
| 同账户中重复的“科目 + 事项”组合 | **阻断** | 决定保留哪个事项及其历史如何处理；不会自动合并。 |
| 旧事项或新科目的目标分不在 1–199 | **阻断** | 指定有效的当前科目目标分。 |
| 旧数据库已有 `subject_id`、但尚未有新层级表 | **阻断** | 确认该 ID 指向何种旧表并制定专门映射，不能由本迁移猜测。 |
| 历史文本找不到科目或事项、或缺少 `user_id` | review | 接受它作为纯历史快照、在演练副本中补建/人工关联，或批准逐条删除。 |
| 同一科目的历史成绩有多个目标分，或历史目标无效 | review | 确认采用“最新考试日期的有效目标分”；历史成绩不会改写。 |
| `user_id` 指向不存在账户、已有外键违规、跨账户 `subject_id` / `focus_item_id` | **阻断** | 先修复数据归属。 |
| 新层级表本身有重复名称、错误稳定键或事项跨科目账户引用 | **阻断** | 在备份副本中修复，不能由启动时自动修正。 |
| 两个 worker 同时尝试首次 DDL | 不允许 | 正式迁移必须在服务停止后由单个 Python 进程执行。 |
| 迁移导出包升级到 `version: 3` | SQLite 预检不覆盖 | 确认下游消费者接受 `user_subjects`、`user_focus_items` 和 `focus_items`。 |

## 生产前的证据链

先以**候选 release 的代码**对生产数据库做只读预检。候选代码可以放在未切换的 release 目录；不要用旧 `current` 的代码替代候选代码：

```bash
set -euo pipefail
cd /opt/408-dashboard/releases/<candidate-release>
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/preflight_subject_migration.py \
  /opt/408-dashboard/shared/data/dashboard.sqlite3 --json
```

`blocking_risk_count` 或 `review_risk_count` 只要非零，就必须保留完整 JSON 供负责人审查；此时不得迁移、重启或切换 release。只有负责人明确批准每个 review 项，才可继续演练。blocking 项必须先修复。

批准后，建立在线 SQLite 备份，并只在可丢弃的副本演练。若批准删除未关联历史记录，必须先在演练副本执行 `discard_review_history.py`：它要求预检样本完整列出所有未关联行，并要求传入完整、无重复的 `TABLE:ID` 集合和允许的精确快照名称；任何一项与新鲜预检不一致都会回滚。

```bash
set -euo pipefail
sudo mkdir -p /opt/408-dashboard/shared/backups
stamp=$(date +%Y%m%d-%H%M%S)
sudo sqlite3 /opt/408-dashboard/shared/data/dashboard.sqlite3 \
  ".backup /opt/408-dashboard/shared/backups/dashboard-before-focus-hierarchy-${stamp}.sqlite3"
sudo cp /opt/408-dashboard/shared/backups/dashboard-before-focus-hierarchy-${stamp}.sqlite3 \
  /tmp/408-dashboard-focus-hierarchy-rehearsal.sqlite3
sudo chown www-data:www-data /tmp/408-dashboard-focus-hierarchy-rehearsal.sqlite3
cd /opt/408-dashboard/releases/<candidate-release>
# 仅在负责人已明确批准这些精确行时执行；--row 必须覆盖预检中的全部未关联行。
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/discard_review_history.py /tmp/408-dashboard-focus-hierarchy-rehearsal.sqlite3 \
  --row focus_sessions:<id> --expected-subject <snapshot-name> --confirm-discard
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/preflight_subject_migration.py /tmp/408-dashboard-focus-hierarchy-rehearsal.sqlite3 --json
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/migrate_subject_schema.py /tmp/408-dashboard-focus-hierarchy-rehearsal.sqlite3
```

演练输出必须同时满足 `applied: true` 和 `foreign_key_check: []`。保留备份路径、预检 JSON、演练 JSON 和上线后的健康检查结果。

演练成功且获得明确批准后，才可在短维护窗口内串行迁移。若生产预检中的 review 项是已批准丢弃的未关联行，必须再次传入**同一批**精确 `--row` 值；只要预检样本、数量或快照名称发生变化，清理脚本都会拒绝运行。

```bash
set -euo pipefail
sudo systemctl stop 408-dashboard.service
cd /opt/408-dashboard/releases/<candidate-release>
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/preflight_subject_migration.py \
  /opt/408-dashboard/shared/data/dashboard.sqlite3 --json
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/discard_review_history.py /opt/408-dashboard/shared/data/dashboard.sqlite3 \
  --row focus_sessions:<id> --expected-subject <snapshot-name> --confirm-discard
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/preflight_subject_migration.py \
  /opt/408-dashboard/shared/data/dashboard.sqlite3 --json
sudo -u www-data env PYTHONPATH=. /opt/408-dashboard/venv/bin/python \
  scripts/migrate_subject_schema.py \
  /opt/408-dashboard/shared/data/dashboard.sqlite3
```

只有迁移输出确认成功、外键检查为空且候选 release 已切换后，才能启动服务。若迁移失败，保持服务停止，保留数据库备份与诊断结果，不要反复启动 worker 试图绕过阻断。
