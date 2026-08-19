# GroupLLM：LoongArch GCC feature group 合成管线

本模块位于 `extract-llm` 之后、未来的 PoC 实例化模块之前。它面向自有 LoongArch GCC fork 的编译器 CI 质量测试，不是安全测试，也不生成利用代码。

输入是 ExtractLLM 生成的 feature pool。输出不是完整程序，而是可交给下一阶段 InstanLLM 的 feature group：一组不可变的历史 bug-prone source features，加上 GroupLLM 新生成的 glue features、共享执行上下文、依赖图、语义风险和测试 oracle。

设计参考 FeatureFuzz 的 Feature Group Synthesis，但针对当前工程做了增强：论文使用随机采样和微调小模型，本实现使用带语义亲和度与多样性约束的确定性采样，并调用 `.env` 中配置的通用 DeepSeek 大模型。论文原文见 [Discovering 100+ Compiler Defects in 72 Hours via LLM-Driven Semantic Logic Recomposition](https://arxiv.org/abs/2601.12360)。

## 核心不变量

- source feature 不能由模型改写、合并、删除或弱化；最终文件中的原 feature 由本地 candidate 原样复制，并用 SHA-256 校验。
- 每组 source feature 来自不同历史 bug，避免直接复刻原 bug 的 feature 集合。
- 每组必须至少包含两类核心 feature，并通过语言、架构、语义标签、编译阶段、失败模式和证据质量进行候选排序。
- ready group 必须覆盖全部 source feature，且 source/glue feature 必须处在同一个连通依赖图中。
- GroupLLM 只生成 1–4 个 glue features 和组合计划，不生成完整 PoC。
- 无法在同一语言、ABI、ISA、优化选项或测试模式下共存的候选必须返回 `rejected`；拒绝结果留作审计，但不会进入 ready pool。
- 可执行 wrong-code 测试必须检查未定义行为、实现定义行为和非确定性风险。glue feature 只有在未来 PoC 获得新增覆盖后才可晋升回全局 feature pool。

## 目录与产物

```text
group-llm/
├── src/group_llm/             # 采样、API、校验、聚合和 CLI
├── tests/                     # 单元测试
└── out/
    ├── group-candidates.jsonl # 本轮唯一权威 candidate 索引
    ├── candidates/            # 每个 candidate 的完整输入快照
    ├── raw-responses/         # DeepSeek 原始响应，便于 parser 审计
    ├── groups/                # ready、rejected 或 error 的逐组结果
    ├── feature-groups.jsonl   # 仅含通过校验的 ready groups
    ├── feature-groups.json    # 与上面相同的 JSON 数组版本
    ├── feature-group-results.jsonl # 本轮所有 ready/rejected 结果
    ├── feature-group-manifest.json # 最终统计
    ├── feature-coverage.jsonl      # 926 条 feature 的 candidate/ready 覆盖状态
    ├── uncovered-features.jsonl    # 尚未进入 ready group 的下一轮 backlog
    ├── feature-coverage-manifest.json # 覆盖率统计
    └── FEATURE_GROUPS_SUMMARY.md   # 人类可读摘要
```

后续生成 PoC 时，应直接消费 `out/feature-groups.jsonl`，不要扫描 `out/groups/`，因为后者还包含 rejected 审计记录。

## 快速使用

不需要安装第三方 Python 包。以下命令均在本目录执行：

```bash
cd /Users/mac/work/loong-gcc-afl/group-llm
```

1. 建立首批候选：

```bash
PYTHONPATH=src python3 -m group_llm prepare \
  --feature-pool /Users/mac/work/loong-gcc-afl/extract-llm/out/feature-pool.jsonl \
  --groups 64 \
  --min-features 3 \
  --max-features 5 \
  --seed 20260730 \
  --target-profile loongarch
```

相同 feature pool、seed 和参数会得到相同 source feature 组合。默认置信度门槛为 0，支持当前池中出现的 C、C++、Fortran、asm、Ada、D、COBOL、C header、shell、RTL、other 和 unknown，确保第一轮不会静默丢弃低置信度或非主流前端 feature。

继续追加候选时，使用 `candidate` 覆盖基准。它优先选择从未进入任何 candidate 的 feature，直到 `feature-coverage-manifest.json` 中 `candidate_coverage_of_full_pool` 达到 1：

```bash
PYTHONPATH=src python3 -m group_llm prepare \
  --append-groups 96 \
  --coverage-basis candidate \
  --min-confidence 0
```

2. 使用父目录 `.env` 中的真实 DeepSeek 配置生成 group：

```bash
PYTHONPATH=src python3 -m group_llm run \
  --env-file /Users/mac/work/loong-gcc-afl/.env \
  --workers 4 \
  --retries 3
```

需要的变量为：

```dotenv
DEEPSEEK_API_ENDPOINT=https://api.deepseek.com
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=...
```

API key 仅在进程内读取，不会写入 candidate、原始响应、group 或 manifest。默认生成预算为 16000 tokens，因为 reasoning 模型会把内部推理计入 `max_tokens`；预算过低可能出现 `finish_reason=length` 和截断 JSON。

`run` 默认可断点续跑：已经通过校验的 ready/rejected 输出会跳过，parser/API/validation error 会重新请求。单独补跑指定 candidate：

```bash
PYTHONPATH=src python3 -m group_llm run \
  --group-id group-0001-xxxxxxxxxxxx \
  --workers 1
```

只有确实要重新生成有效结果时才使用 `--refresh`。

3. 聚合 ready pool并生成 feature 级覆盖清单：

```bash
PYTHONPATH=src python3 -m group_llm build-groups

PYTHONPATH=src python3 -m group_llm verify \
  --require-outputs \
  --fail-on-error \
  --min-ready-ratio 0.58
```

当候选层已经全覆盖后，使用 `ready` 覆盖基准开启下一轮。它会优先重新组合只存在于 rejected group、尚未进入 ready pool 的 feature：

```bash
PYTHONPATH=src python3 -m group_llm prepare \
  --append-groups 96 \
  --coverage-basis ready \
  --min-confidence 0

PYTHONPATH=src python3 -m group_llm run --workers 6 --retries 3
PYTHONPATH=src python3 -m group_llm build-groups
```

4. 运行单元测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 当前已生成结果

本次真实 DeepSeek 运行对 926 条 ExtractLLM feature 做了全量候选覆盖，并完成一轮针对未 ready feature 的重新组合。最终结果为：

可复现实验使用的精简快照见 `../data/curated/group-llm/`。该目录只保留 ready groups、coverage manifest 和 candidate-only backlog；完整 raw responses 和中间运行目录仍位于本地忽略目录 `out/`，不随交付包发布。

- 492 个候选，926/926 feature 至少被采样一次，candidate 覆盖率 100%；
- 289 个 ready feature groups；
- 203 个 rejected candidates；
- 0 个缺失输出；
- 0 个 API、parser 或 validation error；
- ready groups 共使用 1128 个 source feature 槽位；
- ready 覆盖 751/926 个不同 source features，覆盖率 81.10%；
- 覆盖 190 个不同历史 bug；
- 新生成 748 个 glue features；
- 每个 ready group 平均包含 3.903 个 source features 和 2.588 个 glue features。

ready groups 的语言分布：243 个 C、29 个 C++、6 个 Fortran、5 个 asm、2 个 D、2 个 shell、1 个 Ada、1 个 COBOL。测试模式分布：162 个 `execute_differential`、93 个 `compile_only`、29 个 `assembly_scan`、4 个 `link_test`、1 个 `diagnostic`。

203 个 rejected 不是运行失败。它们主要揭示 soft-float 与 LSX/LASX、lp64s 与 lp64d、不同前端语言、必须报错与必须成功执行、编译器自举条件与用户级 PoC 等不可同时满足的约束。剩余 175 个只完成 candidate 覆盖、尚未进入 ready 的 feature 位于 `out/uncovered-features.jsonl`；下一步应按拒绝原因分流到 build、diagnostic、RTL 或多语言专用 harness，而不是无限随机重组。

`candidate-only` 的精确定义是 `candidate_group_count > 0` 且 `ready_group_count == 0`。当前 175 个 candidate-only features 均至少被尝试组合两次；它们不是未采样记录，也不是 API/parser 失败。

## Feature group schema

每条 ready group 主要包含：

- `group_uid` / `candidate_id`：稳定标识；
- `source_features` / `source_features_sha256`：不可变的 ExtractLLM feature 快照及校验值；
- `group_summary`、`language`、`test_mode`、`target_options`：组合目标；
- `shared_execution_context`：统一的函数、循环、类型、调用链或多翻译单元上下文；
- `preservation_plan`：每个 source feature 的保留位置及不可改变条件；
- `dependencies`：data/control/type/call/target/oracle 依赖边；
- `glue_features`：GroupLLM 新增的胶水语义和短 witness；
- `instantiation_constraints`：下一阶段生成代码必须满足的约束；
- `recommended_oracles`：差分执行、编译成功、诊断或汇编扫描等质量 oracle；
- `semantic_risks`：UB、实现定义行为、ABI/选项冲突和对应缓解方式；
- `generated_by`：模型、响应 ID、token 使用量和生成时间，不包含 API key。

## 交给下一阶段 InstanLLM

后续 PoC 生成器应逐条读取 `feature-groups.jsonl`，并执行以下门禁：

1. 在一个程序或明确的多翻译单元测试中实现全部 `preservation_plan` 和 `dependencies`；
2. 只把 `glue_features.code_witness` 当作示意，不把它误认为完整程序；
3. 对目标编译器运行语法/编译检查，并根据 `test_mode` 执行差分运行、诊断或汇编扫描；
4. 对执行型测试使用 UBSan 或等价检查排除未定义行为，并固定输入保证确定性；
5. 用已有 AFL++ coverage wrapper 测量增量覆盖；
6. 只有带来新增覆盖的 group 才进入优先队列，其 glue feature 才具备回灌 feature pool 的资格；
7. ICE、超时、wrong-code 和异常诊断都作为编译器质量缺陷信号记录，不做安全影响推断。

## AFL edge 反馈闭环

已接入论文式 coverage-guided feedback 的第一版实现：

```bash
PYTHONPATH=src python3 -m group_llm feedback \
  --output-dir out \
  --instan-output-dir ../instan-llm/out
```

该命令读取 InstanLLM 的 AFL edge maps，计算每个 ready group 对 union edge 的增量贡献，并把 reward 拆分到 source features。输出位于 `out/afl-feedback/`，其中 `feature-afl-rewards.jsonl` 会被后续 `prepare` 自动读取，用于提高高价值 feature 在下一轮组合中的采样概率。

如果长程 runner 启用了 AFL++ 原生变异阶段，`group_llm feedback` 还会读取 `out/afl-feedback/native-afl-runs.jsonl`。这类记录来自 `afl-fuzz` 对本轮 covered seed corpus 的 queue replay，属于 batch-level feedback：原生 AFL queue map 的新增 edge 会合入全局 union edge，并平均分配给本轮 seed batch 对应的 source features。它不替代 InstanLLM 的 per-group showmap 归因，而是补充“原生 AFL 在这些 LLM seed 上还能继续打开哪些编译器路径”的信号。

reward 公式：

```text
new_edges(group) = edges(group) - previous_union_edges
new_edges_sum(feature) += new_edges(group) / source_feature_count(group)
reward_score = new_edges_sum + 25.0 * novel_group_count + 0.001 * edge_entries_sum
feedback_bonus = min(8.0, reward_score / 8000.0)
```

`reward_score` 是 feature 级历史贡献分；`feedback_bonus` 是它在下一轮 candidate 采样排序中的加分。reward 不会绕过兼容性检查：language、required target architecture、target options 和 test-mode bucket 不兼容时仍然直接淘汰。新 candidate 会携带 `coverage_feedback` 摘要，并进入 GroupLLM prompt，提示模型优先围绕高 reward features 设计真实数据流、控制流或 target-context 交互。

当前 feedback 只服务 LoongArch C/C++ AFL harness，不会把其他 target 架构或专用前端 feature 全局混入。真实小批测试中，加入 required target arch 与 test-mode hard gate 后，GroupLLM rejected 率从 91.67% 降到 25.00%；9 个新 ready groups 经 InstanLLM 后全部 AFL covered，并新增 1,156 条 union edge。阶段评估见 `../docs/AFL反馈闭环阶段评估.md`。
