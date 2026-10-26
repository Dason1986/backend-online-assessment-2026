# 第一题作答说明

## 运行命令

依赖标准 CPython 3.10+，无第三方依赖。题包脚本以脚本所在目录为 import 根

```text
python3 experiments/run_experiments.py
python3 ../第一题材料/check_result.py ../第一题材料/case.json evidence/fixed_result.json
python3 ../第一题材料/check_platform.py --adapter adapter.json --case ../第一题材料/case.json --out evidence/platform_evidence.json
```

`run_experiments.py` 一键复跑全部实验并汇总到 `evidence/summary.json`。批量入口：`python3 batch_entry.py --case <case.json> --db <库> --out <导出> [--max-new N]`。三个入口脚本自带 sys.path 自适配，`adapter.json` 的 `python3` 命令在嵌入式解释器下亦可运行。

## 修改前诊断（初始记录，编码前写下）

### 问题一：90 件/小时的等待来自消息层还是资源分配？（决定是否做消息队列与高并发改造）

- 当时结论：等待来自调度把两个独立工位当成一条共享时间轴，与消息无关。
- 证据：`legacy_backend.py` 的 `ExecutionWindowPolicy.earliest` 取全局 `MAX(end_s)`；`legacy_trace.csv` 中 J0002 在 S2 上 40s 才开始；`check_result.py` 对随包结果输出双工位利用率各 0.5、最后完成 9600s。
- 待验证项：仅改调度策略、其余不变时吞吐是否翻倍（第四项对照实验）。

### 问题二：240 件/小时目标是否成立？（决定是否建议业务方调整目标）

- 当时结论：不可达。上限 = 2 × 3600 / 40 = 180 件/小时；目标 240 需 9600 工位秒/小时，可用仅 7200。
- 证据：`case.json` 仅两工位、周期 40s，题面明示无共享泵等跨工位约束。
- 待验证项：无算术不确定性；需业务方在"接受 180"与"扩建"间决策。

### 问题三：重复投递、冲突与两进程并发提交如何保证一致？（决定持久层与并发控制设计）

- 当时结论：单一 SQLite 库，`BEGIN IMMEDIATE` 事务串行化提交，同工位时间片在事务内按该工位 `MAX(end_s)` 分配；重复/冲突按 (station_id, ready_s) 判定并写事件。
- 待验证项：`check_platform.py` 的双进程提交、同工位不重叠检查。

## 最终判断（实验后补全）

- 问题一：瓶颈确认在资源分配。对照实验同输入、同窗口 3600s、同硬件约束、同为单进程零消息，唯一变量是调度策略：基线 90 件/小时、利用率 0.5、最后完成 9600s；按工位调度后 180 件/小时、利用率 1.0、最后完成 4800s。若瓶颈在消息层，两版单进程不可能翻倍。等待可逐单追溯：本批全部 ready_s=0，`wait_s` 全部来自工位占用（planned 事件 reason=station_busy），无物料未就绪成分。
- 问题二：240 不可达成立，一期上限 180（实验已触及）。题面禁止缩短周期与增加虚拟工位；扩建每加一工位上限 +90，3 工位即 270 > 240，但扩建时间与数量未定。
- 问题三：`check_platform` 双进程检查通过：同时提交同一任务恰得一 accepted 一 duplicate 且计划一致；同工位并发不重叠；重复/冲突/非法输入结构化可区分。重复导入同一输入（252 条投递）时 240 行计划与最终导出完全一致，重试按契约追加 duplicate 事件，accepted/planned 与计划数不变。

## 一期取舍（评审五条建议）

| 建议 | 处理 | 依据 |
| --- | --- | --- |
| 1 唯一标识、持久记录、追溯恢复 | 应做，已实现 | jobs 主键 + events 追加日志；接续与重导入见证据 |
| 2 六服务 + 消息队列 + 缓存 | 暂缓拆分 | 瓶颈是调度策略不是服务形态；一期保留模块边界（case_loader / plan_store / station_scheduler / task_service）；缓存会制造与 SQLite 的双数据源一致性问题 |
| 3 提升消息并发到 1 万条/秒 | 拒绝 | 单进程零消息已是 90，物理上限 180，消息吞吐无效 |
| 4 无对照实验，先选一个解释推进 | 拒绝做法，改为补实验 | 唯一变量为调度策略的对照实验已区分两种原因（90→180） |
| 5 一期同时交付孪生、全局优化、实时大屏 | 暂缓 | 不解决瓶颈（180 上限已被打满）；"之后再测量等待"顺序错误——wait_s 计划内即可算；运营问题由 get/report 的状态、wait 与事件满足 |

需业务方决定：接受 180 上限并按"达到 180 且工位零空闲"验收一期，或给出扩建工位数量与时间表。

## 接入边界与不变量

- 入口：`adapter.json` → `platform_entry.py`（`--case --db --request --response`，业务错误也写结构化响应并正常退出）；批量入口 `batch_entry.py`；共用 `backend/plan_store.py` 同一持久事实源，指标与事件同源。
- 不变量：job_id 主键唯一；同工位区间互斥（事务内按该工位 `MAX(end_s)` 推进）；`end_s = start_s + cycle_s`；全部时刻 ∈ [0, 2^63−1]，越界返回 `plan_exceeds_time_limit`；新计划恰一条 accepted + planned，重试/冲突恰一条 duplicate / conflict；查询只读。
- 重复判定参数 = (station_id, ready_s)；库绑定 case 签名，不同实验用不同库。并发为单写入者（`BEGIN IMMEDIATE` + busy_timeout 30s），进程交错由 SQLite 锁串行化。已验证正常退出接续；崩溃恢复依赖事务原子性，未注入崩溃（题面不要求）。

## 替代路线

可行替代：最小两服务拆分——"受理/查询 API"与"调度/持久 worker"共享同一 SQLite，HTTP 薄适配器对接契约。选择现路线（单进程模块化 + 文件适配器）的理由：契约明确"本地命令即可、不要求 HTTP 与消息队列"，两周内可交付且运维面最小，模块边界已为拆分留好接缝。

## 证据位置（均在 solution1/ 下）

| 证据 | 位置 |
| --- | --- |
| 基线复跑与检查 | evidence/baseline_rerun.json、check_baseline.json |
| 修复后导出与检查 | evidence/fixed_result.json、check_fixed.json |
| 反例 A（全局 vs 按工位） | experiments/mini_case.json + evidence/mini_global.json、mini_station.json 及两份检查输出 |
| 反例 B（同工位重叠被拒） | experiments/overlap_result.json + evidence/check_overlap.json |
| 接续与重导入 | evidence/resume_step1.json、resume_final.json、resume_reimport.json、summary.json 的 resume 段 |
| 平台一致性 | evidence/platform_evidence.json（passed=true） |
| 汇总 | evidence/summary.json |

反例 A 的错误简化：`earliest = max(ready, 全局 MAX(end_s))` 把两个独立工位当成一条产能时间轴。同一 mini case（80s 窗口、3 任务）下，全局策略 S2 利用率 0.0、完成 2/3，M3 从 80s 才开始；按工位策略 M3 从 0s 开始、S2 利用率 0.5、完成 3/3。反例 B 说明互斥必须由调度器与持久层强制：提交重叠计划，`check_result` 即拒绝（`station:S1: overlap between M1 and M2`），"调用方自律"不可依赖，这是提交路径放入单写入者事务的原因。

## 剩余风险与下一步最小实验

- 未注入崩溃；其他进程持锁超 30s 时 busy_timeout 报错（当前事务毫秒级）。
- `check_platform` 只覆盖公开样例交错，不证明所有并发交错正确。
- 下一步：3—6 工位扩展 case 验证扩展线性度；错峰 ready_s 验证 not_ready 与 waiting 的区分与统计。

## 关键建议的采纳记录

拒绝题面建议 3"先提升消息并发，按每秒一万条建设"。核实：单进程复跑旧原型得 90 件/小时（无消息层），仅替换调度策略（其余不变）得 180 件/小时，证明吞吐由调度策略决定、与消息吞吐无关；叠加产能算术（7200 < 9600 工位秒/小时），该建议对目标完全无效。影响：省去消息队列与缓存一致性问题，预算集中于调度修复、持久接续与契约接入。此结论同样记入 `AI_USAGE.md`。
