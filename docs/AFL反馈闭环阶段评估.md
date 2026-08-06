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
