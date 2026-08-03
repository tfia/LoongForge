# ExtractLLM for LoongArch GCC Quality Features

这个目录把已经归档的 GCC Bugzilla LoongArch 报告整理成 ExtractLLM 可读取的输入，并调用真实 LLM API 生成结构化 feature pool。用途是我们自己 fork 的 GCC 质量测试、CI 覆盖扩展和 ICE/wrong-code 回归发现，不是网络安全测试，也不做攻击性漏洞挖掘。

这里使用的 feature 定义是：

```text
Feature =
  自然语言描述的高层语义不变量
  +
  展示该语义如何实现的代码 witness
```

## 数据流

```text
../gcc-bugzilla-loongarch/archive/reports/bug-*/report.json
  -> out/extract-inputs.jsonl
  -> out/inputs/bug-*.input.json
  -> out/features/bug-*.features.json
  -> out/feature-pool.jsonl
```

`prepare` 会纳入所有已经爬取并保留的 bug report。没有 PoC/testcase 的报告不会被悄悄丢掉，也不会在本地提前跳过；`run` 会把它们同样送入 ExtractLLM，让模型尽量从 bug report 和 fix history 中提取低置信、`synthetic_from_report` 的 feature seed。只有纯文档、脚本维护、外部工具链问题等确实不适合生成编译器测试的报告，才保留为 `insufficient_evidence`。

注意：一条 bug report 不等于一个 feature。一条报告可能同时暴露多个可复用语义不变量，例如“循环中保持不变的值在循环后使用”“sibcall 与寄存器分配交互”“特定 target option 下触发向量模式选择”等。每个 `bug-*.features.json` 里的 `features` 都是数组，`feature-pool.jsonl` 会把它们展平成一行一个 feature，供后续组合采样。

## 快速运行

```bash
cd /Users/mac/work/loong-gcc-afl/extract-llm
uv sync

uv run extract-llm prepare \
  --corpus-dir /Users/mac/work/loong-gcc-afl/gcc-bugzilla-loongarch \
  --output-dir /Users/mac/work/loong-gcc-afl/extract-llm/out

export DEEPSEEK_API_KEY='你的 DeepSeek API key'

uv run extract-llm run \
  --output-dir /Users/mac/work/loong-gcc-afl/extract-llm/out \
  --model deepseek-v4-pro \
  --max-prompt-chars 120000 \
  --keep-going

uv run extract-llm build-pool \
  --output-dir /Users/mac/work/loong-gcc-afl/extract-llm/out

uv run extract-llm verify \
  --output-dir /Users/mac/work/loong-gcc-afl/extract-llm/out \
  --require-outputs \
  --fail-on-api-error
```

API key 只从环境变量读取，不会写入 `out/` 或源码文件。`out/raw-responses/` 保存 DeepSeek 返回体，方便追溯 token usage 和模型响应；里面也不包含 API key。

## 小批量验证

先跑 1 条真实 API smoke test：

```bash
uv run extract-llm run \
  --output-dir /Users/mac/work/loong-gcc-afl/extract-llm/out \
  --bug-id 106096 \
  --refresh

uv run extract-llm build-pool --output-dir /Users/mac/work/loong-gcc-afl/extract-llm/out
uv run extract-llm verify --output-dir /Users/mac/work/loong-gcc-afl/extract-llm/out
```

断点续跑时不要加 `--refresh`，已存在的 `out/features/bug-*.features.json` 会自动跳过。

`--max-prompt-chars` 只限制发给模型的 JSON 视图，完整输入仍保留在 `out/extract-inputs.jsonl` 和 `out/inputs/`。超长报告会优先保留 PoC、fix history 和关键评论，避免批量调用时触发上下文长度错误。

## 输出格式

每个 bug 的 feature 文件形如：

```json
{
  "schema_version": 1,
  "bug_id": 106096,
  "extraction_status": "ok",
  "root_cause_summary": "The epilogue clobbered a temporary register that was still available for sibling calls.",
  "evidence_gaps": [],
  "features": [
    {
      "feature_id": "F1",
      "description": "A function should perform a sibling call while preserving the backend's epilogue temporary register from allocation as a call target register.",
      "code_witness": "struct path_range_query { void ssa_range_in_phi(vrange &); bool m_resolve; }; ...",
      "language": "c++",
      "compiler_area": "target",
      "failure_mode": "wrong-code",
      "target_options": ["-O2"],
      "root_cause_link": "The witness can force sibcall/register allocation interactions that exposed SIBCALL_REGS including LARCH_PROLOGUE_TEMP.",
      "source_program_ids": ["bug-106096-poc-001"],
      "source_comment_numbers": [11],
      "confidence": 0.88
    }
  ]
}
```

全局池 `out/feature-pool.jsonl` 是一行一个 feature，包含 `feature_uid`、`bug_id`、`root_cause_summary` 和 `feature` 对象，适合后续按 compiler area、failure mode、语言和 target option 进行采样组合。

## 常用命令

查看 feature 数量和分类：

```bash
jq '.counts' /Users/mac/work/loong-gcc-afl/extract-llm/out/feature-pool-manifest.json
```

抽取某个 bug 的 feature：

```bash
jq '.features[] | {description, language, compiler_area, failure_mode}' \
  /Users/mac/work/loong-gcc-afl/extract-llm/out/features/bug-106096.features.json
```

按向量化相关 feature 粗筛：

```bash
rg -n 'vector|SIMD|LSX|LASX|lsx|lasx' \
  /Users/mac/work/loong-gcc-afl/extract-llm/out/feature-pool.jsonl
```

## 质量边界

- 输入来自公开 GCC Bugzilla 和本地 GCC testsuite 归档，保留来源 URL、PR 编号和 testcase SHA-256。
- ExtractLLM prompt 明确要求输出 compiler quality feature，不要求也不鼓励安全利用路径。
- 对没有 PoC 或缺少明确 fix history 的报告，输出会记录 `evidence_gaps`，避免把猜测混进高置信 feature pool。
- 后续接 AFL 时，LLM 应作为异步数据准备环节，不放在 AFL 热路径；AFL/CI 只消费已经落盘并审核过的 feature pool。

## 2026-07-22 实跑结果

本次使用 DeepSeek 官方 OpenAI-compatible Chat Completions endpoint 和 `deepseek-v4-pro` 对归档报告做了真实 API 抽取，并把提取方式改为更适合 PoC 重组的 feature 原子拆分：

- 输入报告：214 条；
- 最终输出文件：214 个；
- `ok`：198 条；
- `insufficient_evidence`：16 条，主要是纯文档/脚本维护、外部工具链或不可转化为编译器测试的问题；
- `parse_error`：0 条，5 条模型 JSON 小破损已从 raw response 本地修复；
- `api_error`：0 条，尾段 11 条 `HTTP 402 Insufficient Balance` 已换 DeepSeek key 补跑完成；
- 当前 feature pool：926 个 feature；
- 多 feature 报告：178 条 bug report 产出了 2 个或更多 feature，单条报告最多 8 个 feature。

关键文件：

- `/Users/mac/work/loong-gcc-afl/extract-llm/out/extract-inputs.jsonl`
- `/Users/mac/work/loong-gcc-afl/extract-llm/out/features/bug-*.features.json`
- `/Users/mac/work/loong-gcc-afl/extract-llm/out/feature-pool.jsonl`
- `/Users/mac/work/loong-gcc-afl/extract-llm/out/feature-pool-manifest.json`
- `/Users/mac/work/loong-gcc-afl/extract-llm/out/FEATURE_POOL_SUMMARY.md`
