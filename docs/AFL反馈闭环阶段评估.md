# AFL edge 反馈闭环阶段评估

日期：2026-08-12

测试范围：自有 LoongArch GCC fork 的编译器 CI 质量测试；不涉及网络安全测试。

## 目标

对齐论文中的 coverage-guided feedback loop：不只在 InstanLLM 后端统计 AFL edge，而是把“哪些 feature group / source feature 贡献了新增 AFL union edge”反馈给 GroupLLM 的下一轮特征选取与组合。

当前实现暂不继续扩展 gcov 源码覆盖率。gcov 用于质量汇报，AFL edge 用于 fuzz/corpus admission 和前端反馈。

## 已实现的反馈链路

1. `group_llm feedback` 读取：
   - `group-llm/out/feature-groups.jsonl`
   - `instan-llm/out/evaluations.jsonl`
   - `instan-llm/out/coverage/*.map`
   - 可选的 `group-llm/out/afl-feedback/native-afl-runs.jsonl`
2. 对每个 covered group 计算：
   - 单测例 edge entries；
   - 相对历史 union edge 的新增 edge；
   - union edge 累计值；
   - 是否提升该 group 的 glue features。
3. 将新增 edge 奖励拆分到 source features，输出：
   - `group-llm/out/afl-feedback/group-afl-feedback.jsonl`
   - `group-llm/out/afl-feedback/feature-afl-rewards.jsonl`
   - `group-llm/out/afl-feedback/novel-glue-features.jsonl`
4. 如果启用 AFL++ 原生变异阶段，则在 InstanLLM showmap 评估后运行 `afl-fuzz`，再用 `afl-showmap` 重放 AFL queue，生成 queue-level edge map。该 map 的新增 edge 作为 batch-level feedback 合入 union edge，并平均分配给本轮 seed batch 对应的 source features。
5. `group_llm prepare` 自动读取上述 `feature-afl-rewards.jsonl`，在后续候选采样中提高高 reward feature 的优先级。

核心原则：AFL edge feedback 只服务当前可执行的 LoongArch C/C++ AFL harness。Fortran/Ada/D/COBOL/shell、其他 target 架构、build/link 级专用场景不会被无差别混入当前反馈迭代。

当前 InstanLLM 评估口径已按质量测试要求切到更激进的优化路径：默认用 `-Ofast` 重放 generated programs。实现方式是在 AFL showmap 评估前统一清理原有 `-O*` 选项并前置 `-Ofast`；如需要复现实验中的原始模型选项，可显式传 `--optimization=preserve`。

2026-08-19 已新增可选 AFL++ native mutation 阶段。默认不开启，保持历史 showmap-only 大闭环；传入 `--native-afl-seconds N` 后，每轮会把本轮 InstanLLM covered 的 C/C++ 程序复制成 seed corpus，调用 `scripts/run-gcc-afl-fuzz.sh` 运行原生 `afl-fuzz`，然后用 `scripts/afl-coverage-report.sh` 重新计算 queue coverage。反馈归因粒度如下：

- InstanLLM showmap：per-group 归因，适合计算每个 feature group 的直接新增 edge；
- native AFL queue map：batch-level 归因，因为 AFL queue 中多代变异样例不总能可靠还原到唯一 source feature，所以新增 edge 平均分给本轮 seed batch 的 source features；
- 两者最终进入同一个 `feature-afl-rewards.jsonl`，下一轮 GroupLLM 仍通过同一 reward 机制采样。

## reward 如何计算

reward 的目标不是给某个 feature 做严格因果归因，而是提供一个工程上稳定的启发式信号：历史上参与过“新增 AFL edge”的 source feature，在下一轮组合时应更优先被考虑。

### 1. group 级新增 edge

对 InstanLLM 已经标记为 `covered` 的每个 group，按 `evaluations.jsonl` 中的顺序读取 AFL map：

```text
edges(group_i) = 该测例触发的 AFL edge 集合
global_edges_before_i = i 之前所有 covered 测例的 union edge 集合
new_edges(group_i) = edges(group_i) - global_edges_before_i
```

因此：

- `edge_entries`：这个测例自己的 AFL edge 数；
- `new_edges`：这个测例相对历史 corpus 新增的去重 edge 数；
- `new_edge_ratio = new_edges / edge_entries`；
- `union_edges_after`：加入该测例后的累计 union edge。

如果 `new_edges > 0`，说明这个 group 确实打开了此前 corpus 没有覆盖到的编译器执行路径。

### 2. source feature 级奖励分配

一个 group 由多个历史 source features 和若干 GroupLLM glue features 组成。当前实现把 group 的新增 edge 平均分给组内 source features：

```text
reward_share(feature_j in group_i) = new_edges(group_i) / source_feature_count(group_i)
```

这样设计的原因：

- 当前阶段无法精确证明某条 edge 是哪个 feature 单独贡献的；
- 论文也把 coverage gain 视为 feature group 潜力信号，而不是单 feature 的严格因果证明；
- 均分策略简单、可解释、稳定，不会让某个 feature 因模型输出细节被过度归因。

每个 feature 会累计以下字段：

| 字段 | 含义 |
| --- | --- |
| `covered_group_count` | 这个 feature 出现在多少个 AFL covered groups 中 |
| `novel_group_count` | 这个 feature 出现过多少个 `new_edges > 0` 的 groups |
| `edge_entries_sum` | 参与 group 的 edge entries 总和 |
| `new_edges_sum` | 从各 group 均分得到的新增 edge 累计 |
| `max_group_new_edges` | 参与过的 group 中最大单次新增 edge |

### 3. 最终 reward_score

写入 `feature-afl-rewards.jsonl` 的最终分数是：

```text
reward_score =
  new_edges_sum
  + 25.0 * novel_group_count
  + 0.001 * edge_entries_sum
```

三部分分别代表：

1. `new_edges_sum`：核心信号，表示该 feature 参与组合后实际带来的新增 AFL union edge。
2. `25.0 * novel_group_count`：稳定性奖励。一个 feature 多次参与“有新增 edge”的 group，比只在单个大 group 中偶然拿到高分更可信。
3. `0.001 * edge_entries_sum`：弱信号。即使没有新增 union edge，一个 feature 参与的测例如果能稳定触发较深编译路径，也保留少量优先级；权重很小，避免它压过真正的新增 edge。

示例：一个 feature 参与了 2 个 covered groups，其中一个 group 新增 100 edges、含 4 个 source features，另一个 group 新增 0 edges；两个 group 的 edge entries 合计 20,000，则：

```text
new_edges_sum = 100 / 4 + 0 = 25
novel_group_count = 1
edge_entries_sum = 20,000
reward_score = 25 + 25 * 1 + 0.001 * 20,000 = 70
```

这个分数表示：它不是直接保证下一次会发现 bug，而是说明“这个 feature 曾经参与过能打开新 compiler path 的组合”，下一轮应该提高采样优先级。

## reward 如何生效

`group_llm prepare` 会自动读取：

```text
group-llm/out/afl-feedback/feature-afl-rewards.jsonl
```

也可以通过 `--feedback-rewards` 显式指定。

采样时 reward 通过两层方式生效。

### 1. 先限制反馈适用范围

当前 AFL evaluator 只覆盖 LoongArch C/C++ harness，因此 feedback 不会全局作用到所有 feature。采样器先过滤到当前 harness 兼容池：

- language 属于 C/C++/asm/c-header/unknown/other 中可落入当前 C/C++ 生成链路的范围；
- required target architecture 必须是 LoongArch，或没有明确 required target；
- 排除 Go/gccgo/libgo、unsupported-target fixed-point、MIPS `-mips32`/`mips64`、x86 hard register / `__builtin_ia32` / MXCSR、big-endian `_BitInt`、GCC plugin、dlopen/shared/pthread 等需要专用 harness 或非 LoongArch target 的 feature；
- pair 级别还要求 language、required architecture、target options、test-mode bucket 兼容。

这一步是降低 rejected 率的关键。第一版全局 reward 加权会把 x86、m68k、PowerPC、COBOL 等高 reward feature 与 LoongArch feature 混在一起，导致 GroupLLM 正确拒绝。现在 reward 只在“能被当前 harness 测”的空间内发挥作用。

### 2. 在 candidate_selection_score 中加分

每次向一个 candidate group 加入新 feature 时，采样器会计算综合分：

```text
candidate_selection_score =
  max_pair_affinity
  + 0.35 * mean_pair_affinity
  + feature_type_novelty
  + uncovered_bonus
  + underuse_bonus
  + target_profile_bonus
  + feedback_bonus
```

其中 feedback 部分是：

```text
feedback_bonus = min(8.0, reward_score / 8000.0)
```

也就是说，reward 不是硬规则，而是排序加分：

- 如果 pair affinity、target/options/test-mode 不兼容，直接淘汰，reward 再高也不能进入 group。
- 如果 feature 兼容且语义相关，reward 会提高它进入下一轮组合的概率。
- `feedback_bonus` 最大封顶 8 分，避免一个历史高覆盖 feature 垄断所有组合。

这也是向领导解释 reward 时最重要的一点：reward 是“覆盖反馈驱动的排序信号”，不是“越高越必须组合”的硬命令。硬约束仍然优先，包括目标架构、ABI、优化选项、测试模式、语言前端和 harness 能力。这样可以避免把历史上高覆盖但目标不兼容的 feature 强行组合成无效 PoC。

### 3. 写入 candidate，交给 GroupLLM 参考

生成的新 candidate 会携带：

```json
"coverage_feedback": {
  "basis": "afl_union_edge_reward",
  "source_features": [
    {
      "feature_uid": "...",
      "reward_score": 123.0,
      "new_edges_sum": 80.0,
      "novel_group_count": 2
    }
  ],
  "max_reward_score": 123.0
}
```

这份摘要也会进入 GroupLLM prompt。作用是告诉模型：这些 source features 曾经参与过新增 coverage 的组合，生成 glue/dependency plan 时应优先让它们发生真实数据流、控制流、类型或 target-context 交互，而不是简单并排摆放。

可以对领导这样概括：

> 我们不是让 LLM 随机组合 feature，而是把 AFL 测出来的新增控制流边回写成 feature reward。下一轮 GroupLLM 会在 LoongArch C/C++ 可测空间内优先选择高 reward feature，并要求它们通过数据流、控制流或 target context 形成新组合。reward 只影响排序，不绕过兼容性检查，所以既能利用覆盖反馈，又能控制 rejected 率。

## rejected 率修复

第一版 feedback 只按 feature reward 全局加权，导致多个高覆盖但不同 target/language/test-mode 的 feature 被强行放进同一 group。真实 GroupLLM 小批测试结果：

| 批次 | 采样策略 | GroupLLM ready | GroupLLM rejected | rejected 率 |
| --- | --- | --- | --- | --- |
| 初版 feedback | 全局 reward 加权 | 1/12 | 11/12 | 91.67% |
| 第一轮修复 | 限制到当前 AFL harness 兼容池 | 7/12 | 5/12 | 41.67% |
| 第二轮修复 | 增加 required target arch 与 test-mode hard gate | 9/12 | 3/12 | 25.00% |
| 2026-08-12 校准批 | 继续观察隐性 target/plugin/endianness 冲突 | 8/16 | 5/16 | 31.25% |

2026-08-12 校准批显示，剩余 rejected 主要来自更隐蔽的硬约束混组：LoongArch 与 MIPS32/x86 hard register、little-endian LoongArch SIMD 与 big-endian `_BitInt`、GCC plugin/analyzer 与执行/汇编扫描 oracle 等。已把这些原因继续沉淀为本地过滤规则：

- `required_architecture_set()` 新增 MIPS 与 x86 hard register 识别；
- `feedback_iteration_compatible()` 排除 MIPS、x86 hard register、big-endian、GCC plugin 等当前 harness 不能测的 feature；
- `sample_candidate_groups()` 在组内新增 pairwise `options_compatible()` 与 `test_modes_compatible()` hard gate，避免把明显冲突的 feature 送给 LLM 再拒绝。

这些修改是对原有 GroupLLM 采样路径的直接增强，没有新增冗余管线链路。

## 真实 LLM + AFL 效果

第二轮修复后的 12 个 feedback-guided GroupLLM candidates 中，9 个成为 ready groups，且全部进入当前 C/C++ InstanLLM 流程。

InstanLLM 结果：

| 指标 | 数值 |
| --- | --- |
| 新增 GroupLLM ready groups | 9 |
| InstanLLM ready | 9 |
| AFL++ covered | 9 |
| InstanLLM ready 率 | 100.00% |
| AFL covered 率 | 100.00% |

AFL edge 结果：

| 指标 | 数值 |
| --- | --- |
| 历史 covered corpus | 260 |
| 历史 mixed-optimization union edge | 261,917 |
| feedback 后 covered corpus | 269 |
| feedback 后 mixed-optimization union edge | 263,073 |
| feedback 带来的 mixed-optimization 新增 edge | 1,156 |
| 2026-08-12 `-Ofast` 统一重放 covered corpus | 269 |
| 2026-08-12 `-Ofast` 统一重放 union edge | 260,124 |

新增测例明细：

| candidate | language | edge entries | 新增 edge |
| --- | --- | --- | --- |
| `group-0529-a11a75c46ae8` | c | 3,390 | 0 |
| `group-0530-5a84eabc2cb8` | c | 3,368 | 0 |
| `group-0531-156cec5c0d07` | c | 18,008 | 19 |
| `group-0533-ddf43aaba425` | c | 82,985 | 174 |
| `group-0534-0faaf3313288` | c++ | 24,912 | 948 |
| `group-0536-f05bee7b796f` | c | 3,509 | 6 |
| `group-0537-fe61918e3310` | c | 3,376 | 0 |
| `group-0538-e9a09166f242` | c | 40,099 | 6 |
| `group-0539-98f8ceaa9d33` | c | 3,366 | 3 |

解读：

- feedback-guided loop 已经能把新增 AFL edge 反馈到特征组合阶段，并产出新的 covered corpus。
- 新增 9 个测例中 6 个带来 AFL union edge 增量，说明 feedback 并非只是在重复已有路径。
- 最大单例 `group-0534` 新增 948 edges，说明 C++ 侧仍有较大未探索空间，后续可单独加强 C++ feature grouping。
- rejected 率从 91.67% 降到 25.00%，说明 GroupLLM 侧的 target/test-mode hard gate 是必要的；后续继续把 rejected 原因回流成本地规则，而不是让 LLM 反复判断显然不兼容的组合。
- `-Ofast` 统一重放后的 union edge 与 mixed-optimization 数值不能直接当作同一基线比较。它们是不同 compiler option 口径下的 AFL map：`-Ofast` 会改变前端/优化 pass 路径，部分原有边消失、部分新边出现。因此后续趋势比较应固定在 `-Ofast` 口径，以 260,124 作为当前基线。

## 2026-08-12 至 2026-08-13 长程 `-Ofast` 迭代结果

按领导建议切换到 `-Ofast` 后，先完成两轮基线长程迭代；随后在 2026-08-13 更换 provider，并把并发提高到 GroupLLM 6、InstanLLM 4 后继续跑 3 个大轮次。第 1 个并发轮次消费了此前未执行的 backlog（`group-0682` 到 `group-0729`），其中 timeout group 已按要求补跑；第 2/3 个并发轮次各追加 48 个新 candidates。三轮结束后停止，没有继续开新轮。

总体结果：

| 指标 | `-Ofast` 初始基线 | 08-12 两轮后 | 08-13 第 1 并发轮后 | 08-13 第 2 并发轮后 | 08-13 第 3 并发轮后 |
| --- | ---: | ---: | ---: | ---: | ---: |
| AFL covered corpus | 269 | 345 | 389 | 429 | 471 |
| AFL union edges | 260,124 | 288,889 | 296,181 | 298,409 | 299,954 |
| 相对上一阶段新增 edges | - | +28,765 | +7,292 | +2,228 | +1,545 |
| 相对上一阶段增长率 | - | +11.06% | +2.52% | +0.75% | +0.52% |
| 相对 `-Ofast` 初始基线累计新增 edges | - | +28,765 | +36,057 | +38,285 | +39,830 |
| 相对 `-Ofast` 初始基线累计增长率 | - | +11.06% | +13.86% | +14.72% | +15.31% |
| ICE-like crash | 0 | 0 | 0 | 0 | 0 |

08-13 三轮并发长程链路质量：

| 轮次 | candidates | GroupLLM ready | GroupLLM rejected | GroupLLM parse/error/timeout | InstanLLM ready/covered | skipped/not-ready | ICE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 第 1 并发轮（补跑后） | 48 | 46 | 2 | 0 | 44 | 2 | 0 |
| 第 2 并发轮 | 48 | 44 | 4 | 0 | 40 | 4 | 0 |
| 第 3 并发轮 | 48 | 43 | 4 | 1 parse_error | 42 | 1 | 0 |
| 合计 | 144 | 133 | 10 | 1 | 126 | 7 | 0 |

08-13 并发效率数据：

| 轮次 | 近似 wall time | GroupLLM jobs | GroupLLM 平均耗时 | GroupLLM 最长耗时 | InstanLLM jobs | InstanLLM 平均耗时 | InstanLLM 最长耗时 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 第 1 并发轮（含补跑） | 约 0.99 小时 | 48 + 2 补跑 | 165.4 秒 | 420.0 秒（初跑 timeout） | 44 + 5 补跑 | 117.2 秒 | 480.0 秒（初跑 timeout） |
| 第 2 并发轮 | 约 1.08 小时 | 48 | 243.7 秒 | 589.9 秒 | 44 | 141.8 秒 | 668.4 秒 |
| 第 3 并发轮 | 约 0.95 小时 | 48 | 199.2 秒 | 606.0 秒 | 43 | 140.8 秒 | 533.3 秒 |

说明：

- 并发从 GroupLLM 4 / InstanLLM 2 提到 GroupLLM 6 / InstanLLM 4 后，单轮 wall time 从此前约 2.4–2.6 小时下降到约 0.95–1.08 小时；三轮含补跑总 wall time 约 3.04 小时。
- 第 1 并发轮初跑时有 2 个 GroupLLM process timeout 和 3 个 InstanLLM process timeout；按要求放宽 timeout 后补跑，5 个全部进入 covered，因此最终统计按补跑后 `covered=389`、`union_edges=296,181` 计算。
- 第 2/3 并发轮使用 `--group-process-timeout 720`、`--instan-process-timeout 720` 和 `--instan-retries 2`，没有再出现 process timeout。第 3 轮只有 1 个 GroupLLM parse_error，原因是 provider 返回 JSON 字符串截断；其余请求正常。
- 当前 AFL union edge 增长已经明显进入边际递减区间：08-13 三轮依次新增 +7,292、+2,228、+1,545。短期更有效的方向不是无控制增加轮数，而是提高 oracle 质量、修复 InstanLLM not-ready/rejected、并为 assembly-scan/diagnostic/多语言 group 补齐专用 harness。
- 当前没有发现 ICE-like crash。所有 `instan-llm/out/evaluations.jsonl` 中的状态为 `covered=471`、`skipped_not_ready=27`、`ice=0`。


## 2026-08-13 并发长程三轮变化表

| 轮次 | candidates | GroupLLM ready | InstanLLM/AFL covered | AFL union edge 起点 | AFL union edge 终点 | 新增 edge | ICE | 近似 wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 第 1 并发轮（含 timeout 补跑） | 48 | 46 | 44 | 288,889 | 296,181 | +7,292 | 0 | 约 0.99 小时 |
| 第 2 并发轮 | 48 | 44 | 40 | 296,181 | 298,409 | +2,228 | 0 | 约 1.08 小时 |
| 第 3 并发轮 | 48 | 43 | 42 | 298,409 | 299,954 | +1,545 | 0 | 约 0.95 小时 |
| 合计 | 144 | 133 | 126 | 288,889 | 299,954 | +11,065 | 0 | 约 3.04 小时 |

并发优化后，GroupLLM 并发为 6、InstanLLM 并发为 4。第 1 并发轮初跑 timeout 的 5 个子任务已补跑成功；第 2/3 轮放宽 process timeout 到 720 秒后没有再出现 process timeout。三轮 edge 增量递减，说明当前 corpus 已开始进入边际收益下降区间，后续应优先提高 oracle、补齐专用 harness、降低 not-ready/rejected，而不是单纯无限加轮数。

## 2026-08-19 打开 AFL++ 原生变异后的两轮对比

本轮按要求只使用当前 LoongArch feature pool，新增打开 AFL++ 原生 fuzz 的可选阶段。运行命令：

```bash
scripts/run-afl-feedback-loop.py \
  --iterations 2 \
  --batch-size 48 \
  --group-parallel 6 \
  --group-api-timeout 180 \
  --group-process-timeout 720 \
  --group-retries 2 \
  --group-max-tokens 32000 \
  --group-max-witness-chars 1800 \
  --instan-workers 4 \
  --instan-timeout 180 \
  --instan-process-timeout 720 \
  --instan-retries 3 \
  --instan-max-tokens 32000 \
  --evaluate-timeout-ms 30000 \
  --optimization=-Ofast \
  --coverage-basis ready \
  --native-afl-seconds 180 \
  --native-afl-languages c \
  --native-afl-timeout 5000+
```

日志目录：`/Users/mac/work/loong-gcc-afl/logs/afl-feedback-loop/20260819-163452`。

### 与不开原生 fuzz 的历史结果对比

| 运行口径 | 轮数 | candidates | GroupLLM ready | InstanLLM/AFL covered | AFL union edge 起点 | AFL union edge 终点 | 新增 edge | ICE | 近似 wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 08-13 showmap-only 并发三轮 | 3 | 144 | 133 | 126 | 288,889 | 299,954 | +11,065 | 0 | 约 3.04 小时 |
| 08-19 native AFL enabled 两轮 | 2 | 96 | 23 | 13 | 299,954 | 307,099 | +7,145 | 0 | 约 2.10 小时 |

注意：08-19 两轮的 GroupLLM ready 率明显低于 08-13，并非 native AFL 阶段导致，而是当前 provider 在 GroupLLM 并发 6、`--group-api-timeout 180` 下出现大量读超时。两轮 GroupLLM 进程返回码均为 0，但输出状态中分别有 33 和 32 个 `api_error`，错误均为 `DeepSeek request failed: The read operation timed out`。

### 08-19 分轮结果

| 轮次 | GroupLLM 状态 | InstanLLM/AFL 状态 | native AFL seed | native AFL queue inputs | native AFL queue edges | union edge 起点 | union edge 终点 | 新增 edge | ICE |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 第 1 轮 | ready 13 / rejected 2 / api_error 33 | covered 9 / skipped_not_ready 4 | 9 | 1,336 | 125,507 | 299,954 | 304,942 | +4,988 | 0 |
| 第 2 轮 | ready 10 / rejected 5 / validation_error 1 / api_error 32 | covered 4 / skipped_not_ready 6 | 4 | 1,437 | 87,268 | 304,942 | 307,099 | +2,157 | 0 |
| 合计 | ready 23 / rejected 7 / validation_error 1 / api_error 65 | covered 13 / skipped_not_ready 10 | 13 | 2,773 | - | 299,954 | 307,099 | +7,145 | 0 |

### 新增 edge 归因拆分

| 来源 | feedback rows | edge entries sum | 对 union 的新增 edge |
| --- | ---: | ---: | ---: |
| InstanLLM showmap per-group | 18 | 349,262 | +1,135 |
| native AFL queue map batch-level | 2 | 212,775 | +6,043 |
| 合计近似 | 20 | 562,037 | +7,178 |

合计近似值比两轮 union delta `+7,145` 多 33 条，来自全局 feedback 重新构建时历史 evaluation 顺序和本轮 run-summary 采样窗口的边界差异；趋势判断不受影响。关键结论是：本次打开 native AFL 后，新增覆盖主要来自 AFL++ 原生变异队列，而不是单纯来自 LLM 新生成样例。

native AFL 自身健康指标：

| 轮次 | execs_done | execs_per_sec | corpus_count | corpus_found | AFL edges_found | bitmap_cvg | stability | crashes | hangs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 第 1 轮 | 25,245 | 140.19 | 1,331 | 1,322 | 125,510 | 8.21% | 99.99% | 0 | 0 |
| 第 2 轮 | 27,498 | 152.75 | 1,436 | 1,432 | 87,279 | 5.71% | 100.00% | 0 | 0 |

解读：

- 原生 AFL 阶段已经成功接入同一 feedback 链路：`group_llm feedback` 读取 `native-afl-runs.jsonl`，把 queue-level 新增 edge 合入 `feature-afl-rewards.jsonl`，下一轮 GroupLLM 会消费同一 reward 文件。
- 08-13 showmap-only 已进入边际递减区间，三轮平均每个 covered 新增约 87.8 edges；08-19 在 ready 率很低、只有 13 个 covered seed 的情况下仍新增 +7,145 edges，说明 AFL 原生变异能从 LLM seed 中继续挖出不少编译器路径。
- 但当前收益受 provider 超时强烈限制。若下一轮目标是提高端到端效率，应优先把 GroupLLM 并发从 6 降到 3-4，或把 `--group-api-timeout` 提高到 300、`--group-retries` 提高到 3，再观察 ready 率；native AFL 本身运行健康，无 crashes/hangs。
- 本轮仍未发现 ICE-like crash。若后续 native AFL queue 中出现 crash，仍要按 signature、source bug PoC 和最小化复核，先判断是否为已知历史 bug 的再覆盖。

## ICE / crash 处理口径

当前 InstanLLM evaluator 已把 GCC `ICE_EXIT_CODE=4` 识别为 `evaluation_status="ice"`。这一步只说明“被测 GCC 前端在该 generated program 上出现了 ICE-like crash”，不能直接宣布发现新 bug。

如果后续长程任务出现 ICE，处理流程是：

1. 保存 generated source、compiler options、AFL map、stderr tail 和 signature hash。
2. 用相同 `cc1/cc1plus`、相同 `-Ofast` 及 target options 复现，排除一次性环境问题。
3. 对比该 group 的 `source_bug_ids`、历史 bug PoC、已有 crash stderr signature 和最小化样例。
4. 如果 signature/触发条件已被现有 bug PoC 覆盖，归类为“老问题被重新覆盖”，可作为回归 corpus。
5. 如果不能被已知 PoC 覆盖，再标记为“新问题候选”，进入最小化和人工确认。

截至 2026-08-12 当前 `-Ofast` 覆盖评估结果中没有 ICE：`covered=269`，`ice=0`。

## 当前长程测试状态

为支持正式大批量测试，新增了可恢复运行器：

```bash
scripts/run-afl-feedback-loop.py \
  --iterations 3 \
  --batch-size 48 \
  --group-parallel 6 \
  --group-api-timeout 180 \
  --group-process-timeout 720 \
  --instan-workers 4 \
  --instan-process-timeout 720 \
  --optimization=-Ofast \
  --native-afl-seconds 180 \
  --native-afl-languages c \
  --native-afl-timeout 5000+
```

这个脚本仍然调用原有 `group_llm prepare/run/build-groups`、`instan_llm run/evaluate` 和 `group_llm feedback`，只是提供分轮、分组、日志和超时保护。它不是新的管线模式。

如果要回到旧口径，省略 `--native-afl-seconds` 或设为 `0` 即可。

2026-08-12 尝试进入长程前，DeepSeek provider 出现明显不稳定：

- 低 timeout 小批：4/4 为 `DeepSeek request failed: The read operation timed out`；
- 提高 timeout 后重跑：出现 `DeepSeek response content was empty` parse_error，并且剩余请求长时间无返回；
- 按操作策略已暂停大批量 LLM 消耗，等待更换 provider 或恢复服务稳定后继续。

恢复后建议先跑 1 轮 8-16 个 group 的校准批；若 ready 率、parse_error 和 api_error 正常，再启动 3 轮以上大批量正式长程任务。

## 下一步

1. 将 feedback-guided prepare 作为下一轮默认迭代策略：先按 AFL reward 选择 anchor，再在同 target/test-mode bucket 内探索新组合。
2. 对新增 edge 为 0 但 oracle 强的程序保留为备选；对新增 edge > 0 的程序优先进入 CI corpus。
3. 单独实现 diagnostic、assembly-scan、build/link、Fortran/asm/RTL harness，避免把这些 feature 强塞到当前 C/C++ AFL harness。
4. 持续把 rejected 原因沉淀为本地 hard gate，减少 LLM token 浪费，提高 ready 率。
