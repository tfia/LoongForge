# GCC Bugzilla LoongArch 历史缺陷语料归档说明

更新日期：2026-07-22

## 项目定位

工作目录新增 `gcc-bugzilla-loongarch/`，用于通过 GCC Bugzilla 官方 REST API 获取 LoongArch/LoongArch64 历史缺陷报告，为团队自有 GCC fork 的自动化质量测试准备可追溯数据。

该工作属于编译器质量工程，不涉及网络扫描、攻击流量、渗透测试或第三方系统测试。

## 产物

- 完整标准化 bug 描述和公开评论；
- Bugzilla 原始搜索、评论和附件元数据；
- Bugzilla 中的复现源码附件和评论 reproducer；
- 本地 GCC testsuite 中按 PR 编号关联的回归测试；
- JSONL、CSV、Markdown 索引和 SHA-256 完整性信息；
- 严格的 `llm-ready.jsonl` 子集，只包含 LoongArch 架构专属、具有明确 LoongArch64 证据、同时具有描述和测试用例，并且未被 Bugzilla 判定为 `INVALID/MOVED` 的报告。
- 可直接消费的 `llm-dataset.jsonl`，每行包含描述、去身份化技术评论、LoongArch64 证据及去重后的 testcase 正文和来源校验信息。
- `llm-expanded-ready.jsonl` 和 `llm-expanded-dataset.jsonl`，在同样的质量门槛下补充多架构共享缺陷、LoongArch testsuite 关联 PR，以及评论中明确报告的 LoongArch 故障。

2026-07-22 扩展正式归档结果：从摘要、Target 字段、公开评论全文和本地 LoongArch testsuite 共发现 216 条候选，完整复核后保留 214 条；其中 134 条具有明确 LoongArch64 证据、138 条包含测试材料、61 条进入严格 LLM-ready、80 条进入扩展 LLM-ready，共整理 448 个带 SHA-256 和来源信息的测试工件。2 条全文搜索假阳性已剔除，归档独立校验通过。

向量扩展方面，全文或测试材料中有 30 条提到 LSX、29 条提到 LASX，去重后 40 条；其中 19 条在标题或 testcase 路径中直接出现 LSX/LASX。严格 LLM-ready 中有 25 条，扩展 LLM-ready 中有 28 条；将一般 vectorization/SIMD 计入后，扩展 LLM-ready 为 36 条。LSX/LASX 有交集，不能把两个数字直接相加。

详细目录、筛选规则、命令和数据治理说明参见 [`gcc-bugzilla-loongarch/README.md`](../gcc-bugzilla-loongarch/README.md)。

## 日常更新

```bash
cd /Users/mac/work/loong-gcc-afl/gcc-bugzilla-loongarch
uv sync
uv run loongarch-bug-corpus sync
uv run loongarch-bug-corpus verify
uv run loongarch-bug-corpus stats
```

同步是增量的：Bugzilla `last_change_time` 未变化时复用已有报告。正式同步禁止使用开发参数 `--limit`。

## 后续接入

后续 LLM 数据准备任务优先读取高精度的 `archive/llm-dataset.jsonl`；需要学习通用优化器缺陷如何在 LoongArch 上暴露时，再读取 `archive/llm-expanded-dataset.jsonl`。LLM 生成的候选测试必须经过本地编译、超时隔离、`afl-showmap` 增量覆盖筛选和人工/自动去重，再进入 CI corpus。
