# AFL edge 反馈闭环阶段评估

日期：2026-08-06

测试范围：自有 LoongArch GCC fork 的编译器 CI 质量测试；不涉及网络安全测试。

## 目标

对齐论文中的 coverage-guided feedback loop：不只在 InstanLLM 后端统计 AFL edge，而是把“哪些 feature group / source feature 贡献了新增 AFL union edge”反馈给 GroupLLM 的下一轮特征选取与组合。

当前实现暂不继续扩展 gcov 源码覆盖率。gcov 用于质量汇报，AFL edge 用于 fuzz/corpus admission 和前端反馈。

## 已实现的反馈链路

1. `group_llm feedback` 读取：
   - `group-llm/out/feature-groups.jsonl`
   - `instan-llm/out/evaluations.jsonl`
   - `instan-llm/out/coverage/*.map`
2. 对每个 covered group 计算：
   - 单测例 edge entries；
   - 相对历史 union edge 的新增 edge；
   - union edge 累计值；
   - 是否提升该 group 的 glue features。
3. 将新增 edge 奖励拆分到 source features，输出：
   - `group-llm/out/afl-feedback/group-afl-feedback.jsonl`
   - `group-llm/out/afl-feedback/feature-afl-rewards.jsonl`
   - `group-llm/out/afl-feedback/novel-glue-features.jsonl`
4. `group_llm prepare` 自动读取上述 `feature-afl-rewards.jsonl`，在后续候选采样中提高高 reward feature 的优先级。

核心原则：AFL edge feedback 只服务当前可执行的 LoongArch C/C++ AFL harness。Fortran/Ada/D/COBOL/shell、其他 target 架构、build/link 级专用场景不会被无差别混入当前反馈迭代。

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
- 排除 Go/gccgo/libgo、unsupported-target fixed-point、MXCSR/dlopen/shared pthread 等需要专用 harness 的 feature；
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

剩余 rejected 主要来自更隐蔽的 target/test harness 需求，例如 RISC-V tag、x86 fixed-point unsupported-target、MXCSR/dlopen 多文件运行时 harness。已继续补充本地过滤规则，避免后续重复采样。

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
| 原 covered corpus | 260 |
| 原 union edge | 261,917 |
| 新增 covered corpus | 9 |
| 新 union edge | 263,073 |
| 新增 union edge | 1,156 |

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

## 下一步

1. 将 feedback-guided prepare 作为下一轮默认迭代策略：先按 AFL reward 选择 anchor，再在同 target/test-mode bucket 内探索新组合。
2. 对新增 edge 为 0 但 oracle 强的程序保留为备选；对新增 edge > 0 的程序优先进入 CI corpus。
3. 单独实现 diagnostic、assembly-scan、build/link、Fortran/asm/RTL harness，避免把这些 feature 强塞到当前 C/C++ AFL harness。
4. 持续把 rejected 原因沉淀为本地 hard gate，减少 LLM token 浪费，提高 ready 率。
