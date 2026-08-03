# GroupLLM 工作上下文接管说明

更新时间：2026-07-30

本文记录当前 GroupLLM 管线的设计口径、权威状态和下一阶段边界，供后续 Codex session 接管。项目用于自有 LoongArch GCC fork 的编译器 CI 质量测试，目标是发现 ICE、wrong-code、异常诊断、编译超时和代码生成退化，不是网络安全测试，也不做漏洞利用或安全影响判断。

## 管线位置与基本对象

当前数据流是：历史 GCC bug report 经 ExtractLLM 拆成 feature pool，GroupLLM 将多个历史 source features 重组为语义相关的 feature group，未来由 InstanLLM 把 ready group 实例化成完整测试程序，再交给 GCC、AFL++ coverage wrapper 和质量 oracle 执行。

这里必须区分以下对象：

- **feature**：ExtractLLM 从一个 bug 中提取的一条独立语义特征，以 `feature_uid` 唯一标识。一个 bug 可以产生多个 features，所以 bug 数、feature 数和 group 数不存在一一对应关系。
- **source feature slot**：某个 feature 在某个 candidate/group 中的一次出现。同一 feature 可以进入多个不同组合，因此 slot 数会大于不同 feature 数。
- **candidate group**：本地确定性采样器选出的 3–5 个不可变 source features。每组中的 features 来自不同历史 bug；候选只表示“已尝试组合”，还没有获得模型的语义可行性认可。
- **ready group**：GroupLLM 判断可以在统一语言、目标选项和测试模式下组成一个连通测试，并且通过本地结构校验的组合。只有 ready group 会进入后续实例化池。
- **rejected group**：GroupLLM 明确判断组合存在语言、ABI、ISA、编译阶段、测试 oracle 或执行条件冲突的候选。rejected 是有效的审计结果，不是 parser/API 错误。
- **candidate-only feature**：至少进入过一个 candidate，但没有出现在任何 ready group 中的 feature。精确定义是 `candidate_group_count > 0` 且 `ready_group_count == 0`。

## 175 个 candidate-only features 的准确含义

当前 feature pool 有 926 个不同 features，全部至少进入过一个候选，因此 candidate 覆盖是 926/926，`never_sampled` 为 0。其中 751 个至少出现在一个 ready group 中；剩余 175 个就是 candidate-only backlog。

这 175 个不能解释为“没有采样”“提取失败”或“丢失”。它们已经被重复尝试：

| 每个 feature 进入 candidate 的次数 | feature 数 |
|---:|---:|
| 2 次 | 142 |
| 3 次 | 22 |
| 4 次 | 8 |
| 5 次 | 3 |

总计 175 个 candidate-only features 在候选中出现了 397 次。当前 API、parser、validation error 均为 0，所以这些 feature 的候选尝试最终都落在 rejected group，而不是因运行错误没有结果。203 个 rejected groups 中有 179 个包含至少一个 candidate-only feature；其余参与 rejected 组合的 feature 可能同时也在别的 ready group 中成功。

candidate-only 按 feature 类型分布：

| feature 类型 | 数量 |
|---|---:|
| `semantic_invariant` | 43 |
| `failure_oracle` | 35 |
| `code_shape` | 27 |
| `pass_interaction` | 24 |
| `target_condition` | 24 |
| `mutation_knob` | 22 |

按原始语言标签分布：C 115、unknown 33、asm 19、C++ 2、Fortran 2、Ada 2、D 1、RTL 1。

它们尚未 ready 的常见原因不是“随机次数还不够”，而是当前统一 group 约束下存在真实冲突，例如：

- soft-float、hard-float、LSX/LASX 或 lp64s/lp64d 不能共用目标选项；
- C/C++/Fortran/asm/RTL 或编译器自举条件不能自然落入同一个用户级源程序；
- compile-only、diagnostic、assembly-scan 和 execute-differential 需要不同 harness；
- 一个 feature 要求编译失败，另一个要求成功执行或检查生成汇编；
- build-system、内部宏或 compiler-bootstrap 条件无法由普通用户代码表达。

因此 `out/uncovered-features.jsonl` 的“uncovered”指尚未被 **ready group** 覆盖，不是尚未被 candidate 采样。下一阶段应首先按拒绝原因分流到 build、diagnostic、RTL、assembly 或多语言专用 harness，再做有约束的重组；不应仅靠无限随机追加候选来追求数字上的 100% ready 覆盖。

## 当前分组的组成

### Candidate 层

当前共有 492 个 candidate groups、1987 个 source feature slots，且 926 个不同 features 已全量覆盖。候选大小分布为：

| 每组 source features | candidate groups |
|---:|---:|
| 3 | 141 |
| 4 | 191 |
| 5 | 160 |

每个 candidate 保存完整且不可变的 source feature 快照、feature UID 列表、不同 source bug ID、SHA-256、主语言、target profile，以及采样亲和度和多样性信息。GroupLLM 不允许改写、合并、删除或弱化这些 source features。

### Ready 层

当前 492 个候选均已有结果：289 个 ready、203 个 rejected，ready ratio 为 58.74%。289 个 ready groups 共含 1128 个 source feature slots，覆盖 751 个不同 features、190 个不同历史 bugs。

ready group 的 source feature 数量分布为：

| 每组 source features | ready groups |
|---:|---:|
| 3 | 102 |
| 4 | 113 |
| 5 | 74 |

一个 ready group 由以下部分共同组成：

1. 3–5 个不可变 `source_features` 及其 SHA-256；
2. 统一的 `language`、`test_mode`、`target_options` 和 `shared_execution_context`；
3. 覆盖每个 source feature 的 `preservation_plan`；
4. 将所有 source/glue 节点连成一个图的 `dependencies`；
5. 1–4 个 GroupLLM 新生成的 `glue_features`，用于建立共享状态、数据/控制流、调用关系、类型桥、target setup 或 oracle scaffolding；
6. `instantiation_constraints`、`recommended_oracles`、`semantic_risks` 和生成元数据。

当前共有 748 个 glue features，平均每个 ready group 2.588 个。分布为：

| 每组 glue features | ready groups |
|---:|---:|
| 1 | 35 |
| 2 | 93 |
| 3 | 117 |
| 4 | 44 |

这些 glue features 只属于 group 内的组合计划，不等同于完整 PoC，也尚未自动回灌全局 feature pool。只有未来实例化后确实带来新增编译器覆盖的 glue，才具备晋升资格。

ready groups 的语言分布为：C 243、C++ 29、Fortran 6、asm 5、D 2、shell 2、Ada 1、COBOL 1。测试模式为：162 个 `execute_differential`、93 个 `compile_only`、29 个 `assembly_scan`、4 个 `link_test`、1 个 `diagnostic`。

### Rejected 层

203 个 rejected groups 保留 source feature 快照和具体 `conflicts`/`notes`，但不进入 `feature-groups.jsonl`，也不交给 InstanLLM。它们是后续改进采样约束和设计专用 harness 的证据，不应删除或与运行错误混为一谈。

## 当前已确认的不变量和修复记录

- 第一阶段 candidate 覆盖已经达到 926/926；后续迭代使用 ready 缺口作为优先级，不再把“是否采样过”和“是否 ready”混成一个指标。
- source feature 快照由本地 candidate 原样复制并校验 SHA-256，模型输出不能修改原始 feature。
- ready group 必须完整 preservation、依赖图连通、目标选项兼容，并具有可执行的质量 oracle 计划。
- ready group 的 glue 数量现在由本地校验器强制限制为 1–4。
- 2026-07-30 审计发现历史 `group-0093-ae1151047059` 曾含 5 个 glue，暴露出提示词有上限但校验器未强制执行的问题。现已补充校验和回归测试，并重新生成该组为 2 个 glue。修复后 13 项单元测试通过，492 个结果完整性验证通过，error/missing 均为 0。
- API key 只从父目录 `.env` 读入进程，不写入任何 candidate、raw response、group、manifest 或文档。

## 权威状态文件

- `out/feature-groups.jsonl`：289 个 ready groups，是未来 InstanLLM 的权威输入。
- `out/feature-group-results.jsonl`：492 个 ready/rejected 结果，用于完整审计。
- `out/feature-group-manifest.json`：group 数量、语言、测试模式、glue role 和覆盖汇总。
- `out/feature-coverage.jsonl`：926 个 feature 的逐条 candidate/ready 覆盖状态。
- `out/uncovered-features.jsonl`：175 个 candidate-only backlog。
- `out/feature-coverage-manifest.json`：candidate/ready 覆盖率及 backlog 分类统计。
- `out/candidates/`、`out/raw-responses/`、`out/groups/`：每个候选的输入快照、模型原始响应和规范化结果。

LoongForge monorepo 已在 `/Users/mac/work/loong-gcc-afl` 初始化，但目录名保持不变以兼容既有脚本。`src/gcc-upstream` 和 `src/binutils-gdb` 作为 Git submodule 管理，当前 commit 记录在顶层 `third_party/SOURCES.lock`。

Git 不跟踪 `group-llm/out/` 的完整运行目录。后续 session 应以本文、上述 manifest，以及顶层 `data/curated/group-llm/` 中的可审计快照为事实来源，不依赖聊天记录里的中间数字。下一阶段的重点是针对 175 个 candidate-only features 的冲突类别设计专用分流/组合策略，以及让 InstanLLM 生成可编译 PoC 并以真实 GCC/AFL++ 覆盖反馈驱动迭代。
