# GCC Bugzilla LoongArch 质量测试语料归档器

该项目通过 GCC Bugzilla 的公开 REST API，归档与 LoongArch/LoongArch64 明确相关的历史 bug report、原始描述、公开评论、复现附件和 GCC testsuite 中按 PR 编号关联的回归测试。

用途是为团队自有 LoongArch GCC fork 建立自动化编译器质量测试数据集，并为后续 LLM 提取 bug 特征、生成新 C/C++ 测试用例提供可追溯输入。它不进行网络扫描、协议攻击、渗透测试或第三方目标测试，不属于网络安全测试。

## 快速开始

```bash
cd /Users/mac/work/loong-gcc-afl/gcc-bugzilla-loongarch
uv sync
uv run python -m unittest discover -s tests -v
uv run loongarch-bug-corpus sync
uv run loongarch-bug-corpus verify
uv run loongarch-bug-corpus stats
```

也可以使用入口脚本：

```bash
uv run ./fetch_loongarch_bugs.py sync
```

首次运行会创建 uv 管理的 Python 3.12 虚拟环境。项目的抓取逻辑只使用 Python 标准库，没有额外运行时依赖。

## 数据范围与分层筛选

发现阶段合并四类证据：

1. Bug 摘要包含 `loongarch`；
2. GCC Bugzilla 的 `Target` 自定义字段 `cf_gcctarget` 包含 `loongarch`；
3. Bugzilla 公开评论全文包含 `loongarch`；
4. 本地 GCC 的 `gcc.target/loongarch`、`g++.target/loongarch` 测试按 `PR<编号>` 关联到通用优化缺陷。

本地筛选会读取完整公开评论，并为每条报告记录证据层级：

- `architecture_specific`：摘要明确提到 LoongArch，或 Target 只包含 LoongArch；
- `multi_arch_shared`：Target 同时包含 LoongArch 和其他架构；
- `loongarch_testsuite_linked`：LoongArch 专属 GCC testsuite 文件明确引用该 PR；
- `loongarch_observed`：同一条公开评论在 LoongArch 上报告失败、ICE、错误代码或复现；
- `loongarch_validation_only`：LoongArch 只出现在测试通过、回归验证、目标列表或一般讨论中；
- `not_loongarch`：完整报告中仍无 LoongArch 证据，不进入归档。

严格核心集仍只接受 `architecture_specific`、具有明确 LoongArch64/LA64/LSX/LASX/LP64 证据、非空原始描述、至少一个可追溯测试用例，且 Bugzilla resolution 不是 `INVALID` 或 `MOVED` 的报告，并标记为 `llm_ready=true`。扩展集还接受 `multi_arch_shared`、`loongarch_testsuite_linked` 和 `loongarch_observed`，但同样要求明确 LoongArch64 证据、描述、测试用例和有效 resolution，并标记为 `expanded_llm_ready=true`。验证型记录保留供审计，不进入两个 LLM 数据入口。`DUPLICATE` 仍可进入，因为重复报告中的独立复现样例对回归测试有价值，原始 bug 关联保存在元数据中。

评论判定要求架构词与故障词出现在同一条评论的局部上下文中；`regression tested on loongarch64` 之类的通过验证不会被误判为 LoongArch 故障。

## 测试用例来源

脚本提取并记录以下来源：

- Bugzilla 中 C/C++、预处理源、Fortran、汇编等源文件附件；
- 摘要标记为 testcase/reproducer/reduced 的公开文本附件；
- 公开评论里的 fenced code block 或明显的 reproducer 文本；
- 本机 GCC checkout 中以 `pr<bug-id>` 命名的 GCC/libstdc++ 回归测试。

每个测试用例都记录来源 URL或 GCC commit、语言、文件大小和 SHA-256。Bugzilla 原始附件与标准化 testcase 分开存放，避免丢失原始文件名和内容。

## 归档结构

```text
archive/
├── SUMMARY.md                      当前归档规模和 LLM-ready 入口说明
├── manifest.json                 本次同步来源、查询、GCC commit、计数和错误
├── index.jsonl                   全部直接相关和多架构相关报告索引
├── index.csv                     便于人工查看的表格索引
├── llm-ready.jsonl               严格满足描述+测试用例条件的报告索引
├── llm-dataset.jsonl             可直接输入 LLM 的描述、评论和去重 testcase 正文
├── llm-expanded-ready.jsonl      包含通用 PR/多架构缺陷的扩展索引
├── llm-expanded-dataset.jsonl    可直接输入 LLM 的扩展数据集
├── raw/                          Bugzilla 版本、三次搜索及 testsuite PR 查询原始响应
└── reports/
    └── bug-112476/
        ├── report.json           机器可读完整标准化报告
        ├── report.md             便于人工和领导审阅的完整报告
        ├── raw/                  bug、comments、attachments 原始 JSON
        ├── attachments/          下载的原始复现附件
        └── testcases/            供 LLM/回归筛选使用的测试用例
```

`report.json` 保留完整公开评论及元数据；`report.md` 包含原始 bug description、测试用例清单、关联证据和评论正文。

## 增量更新

普通同步会比较 Bugzilla `last_change_time`，未变化的报告直接使用本地归档：

```bash
uv run loongarch-bug-corpus sync
```

强制重新获取全部报告：

```bash
uv run loongarch-bug-corpus sync --refresh
```

只重新应用本地筛选策略并重建索引，不访问网络：

```bash
uv run loongarch-bug-corpus rebuild
```

开发时只处理前 5 条候选，不应把该结果作为正式归档：

```bash
uv run loongarch-bug-corpus sync --limit 5 --archive-dir /tmp/loongarch-bug-smoke
```

默认每次 HTTP 请求至少间隔 0.4 秒，并对 429、5xx 和临时网络错误做退避重试。可调整但不建议对 GCC 基础设施施加高并发负载：

```bash
uv run loongarch-bug-corpus sync --delay 1.0 --timeout 120
```

## 完整性验证

```bash
uv run loongarch-bug-corpus verify
```

验证器检查：

- manifest、JSONL、CSV 和每个标准化报告是否存在；
- 归档中是否混入没有 LoongArch 直接证据的报告；
- `llm_ready` 是否同时满足架构专属、明确 LoongArch64 证据、描述非空、测试用例非空，且不是 `INVALID/MOVED`；
- 所有测试文件是否存在且 SHA-256 一致；
- manifest、总索引和 LLM-ready 索引的计数是否一致；
- 扩展索引/数据集是否满足扩展层的架构、描述、测试用例和 resolution 约束；
- 本次同步是否存在未处理的抓取错误。

## 与后续质量流水线的衔接

推荐消费顺序：

1. LLM 直接读取 `llm-dataset.jsonl`，或按 `llm-ready.jsonl` 定位完整 `report.json`；
2. 提取触发条件、目标选项、语言特性、失败阶段、错误类型和修复模式；
3. LLM 离线生成候选测试，保留 bug ID、模型、prompt、随机种子和父样例；
4. 先用普通/插桩 `cc1` 做超时和语法过滤；
5. 用 `afl-showmap` 只保留带来新增边的测试；
6. 对 ICE 设置 `AFL_CRASH_EXITCODE=4`，最小化后纳入长期 CI corpus。

LLM 不应在 AFL 每秒数百次执行的同步热路径中调用。正式 CI 默认消费已审核、已缓存的数据，在线模型生成应放在独立的异步数据准备任务中。

## 2026-07-22 扩展归档结果

- 发现候选：216 条，完整报告复核后保留 214 条，2 条全文搜索假阳性被剔除；
- 架构专属报告：99 条；
- 具备明确 LoongArch64 证据：134 条；
- 含测试材料的报告：138 条；
- 严格 LLM-ready：61 条；
- 扩展 LLM-ready：80 条；
- 测试用例工件：448 个。

向量指令集统计采用三种口径，避免把“只是提到 LoongArch”误算为向量缺陷：

- 全文或测试材料提到 LSX：30 条；提到 LASX：29 条；去重并集 40 条；
- 标题或测试用例路径直接出现 LSX/LASX：19 条，证据最强；
- 严格 LLM-ready 中 LSX/LASX 25 条，扩展 LLM-ready 中 28 条；
- 若把一般 vectorization/SIMD 也计入，共 82 条；扩展 LLM-ready 中 36 条。

LSX 与 LASX 数量不能直接相加，因为同一报告可能同时涉及两种扩展。上述指标由 `rebuild` 写入 `archive/manifest.json` 和 `archive/SUMMARY.md`，不是手工维护。

这些数字由 `archive/manifest.json` 和 `archive/SUMMARY.md` 生成；后续增量同步后以文件中的最新数字为准。

## 数据和许可注意事项

- 数据来自公开 GCC Bugzilla；归档保留来源 URL，禁止把内容标记为团队原创。
- GCC testsuite 文件来自指定 GCC checkout，并记录 commit 与相对路径；再分发和修改时应遵守 GCC 源码中的许可声明。
- Bugzilla 评论可能包含公开提交者邮箱。进入外部 LLM 前，应按团队数据治理规则决定是否做身份字段脱敏；测试代码和技术描述可以与身份元数据分离。
- 自动提取只能证明存在复现材料，不能证明每个历史测试都能直接由当前 compiler-only 工具链执行；进入 CI 前仍需按语言、所需头文件和目标选项二次验证。

## 官方接口

- GCC Bugzilla：<https://gcc.gnu.org/bugzilla/>
- GCC Bugzilla REST：<https://gcc.gnu.org/bugzilla/rest.cgi/version>
- Bugzilla REST Search Bugs 文档：<https://bugzilla.readthedocs.io/en/5.0.4/api/core/v1/bug.html>
