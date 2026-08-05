# LoongArch64 GCC 插桩质量测试工作纪要与 LLM 变异路线图

汇报日期：2026-07-21
工作目录：`/Users/mac/work/loong-gcc-afl`

仓库名：`loongforge`。当前已将上述工作目录初始化为单仓库 monorepo，但保留原目录名，避免破坏已有脚本和历史报告中的绝对路径。GCC 和 binutils-gdb 源码不直接提交到 monorepo，而是以 `src/gcc-upstream`、`src/binutils-gdb` 两个 Git submodule 锁定版本；具体 commit 见顶层 `third_party/SOURCES.lock`。构建目录、安装目录、AFL 输出、LLM raw outputs 和 `.env` 均由 `.gitignore` 排除，只有代码、文档、脚本、种子和 curated 状态快照进入版本管理。

当前 LLM 管线已扩展为 ExtractLLM -> GroupLLM -> InstanLLM。新增 `instan-llm/` 模块负责读取 GroupLLM 的 ready feature groups，生成完整编译器测试程序，并用 AFL++ wrapped GCC 前端编译记录 edge coverage。只有成功产生非空 coverage map 的 C/C++ 程序会进入 `instan-llm/out/corpus/covered/`，作为后续 CI corpus 候选。

## 一、工作定位与阶段结论

本工作的目标是为团队自有 fork 的 GCC 建立覆盖引导的持续质量测试能力，通过自动生成和变异 C/C++ 输入，尽早发现 ICE、崩溃、编译超时、优化器缺陷及覆盖率回退。

这是编译器质量与 CI 建设，不是网络安全测试：不扫描网络、不生成攻击流量、不测试第三方目标。后续 LLM 也只用于编译器测试用例生成和变异。

本阶段已完成以下关键结果：

- 构建并安装普通 LoongArch64 binutils 和无系统头文件的交叉 GCC；
- 使用 AFL++ 编译器 wrapper 重新构建 GCC 的 C/C++ 前端；
- 安装插桩版 `loongarch64-linux-gnu-gcc/g++`、`cc1/cc1plus`；
- 通过静态符号和动态 `afl-showmap` 两种方式确认插桩生效；
- 完成直接面向 `cc1` 的 AFL++ 质量冒烟测试；
- 建立单样例覆盖、语料累计覆盖、fuzz 启动和质量报告脚本；
- 给出从传统 AFL 变异到 LLM 辅助结构化变异的分阶段实施路线。

## 二、环境与构建对象

| 项目 | 当前状态 |
|---|---|
| 主机 | Apple Silicon macOS，build/host 为 `aarch64-apple-darwin25.5.0` |
| 目标架构 | `loongarch64-linux-gnu` |
| GCC 源码 | commit `913ff90691dbd1a94bb5b205415955dd053279dd` |
| GCC 版本 | 17.0.0 20260718 experimental |
| GNU binutils | 2.47.50.20260718 |
| AFL++ | 5.02c |
| LLVM/Clang | Homebrew LLVM 22.1.8 |
| GNU Make | 4.4.1 |
| Bison | 3.8.2 |
| 普通工具链前缀 | `install/` |
| AFL 插桩工具链前缀 | `install-afl/` |

当前配置是 `--without-headers` 的 compiler-only 交叉工具链，适合解析、语义分析、优化和汇编生成路径的 fuzz。它暂不包含完整 LoongArch sysroot、C 库和目标运行库，因此本阶段不以链接及运行 LoongArch 可执行文件为目标。

## 三、工作过程

### 1. 基础工具和目录准备

安装 Git、GNU Make、Bison、Flex、GMP、MPFR、MPC、ISL、LLVM、AFL++ 等依赖，并建立：

```text
src/          源码
build/        独立构建目录
install/      普通交叉工具链
install-afl/  AFL++ 插桩交叉 GCC
seeds/        初始编译器测试语料
out/          fuzz、覆盖和验证结果
scripts/      可重复执行脚本
docs/         操作说明和汇报材料
```

### 2. 普通 LoongArch64 binutils

binutils 使用以下核心配置：

```bash
src/binutils-gdb/configure \
  --target=loongarch64-linux-gnu \
  --prefix=/Users/mac/work/loong-gcc-afl/install \
  --disable-gdb \
  --disable-gdbserver \
  --disable-sim \
  --disable-nls \
  --disable-werror \
  --with-sysroot=/Users/mac/work/loong-gcc-afl/install/loongarch64-linux-gnu/sysroot
```

首次 `gmake` 的主要问题是 macOS 自带 Bison 2.3 过旧，无法正确处理当前 LoongArch GAS 语法文件。将 PATH 前置到 Homebrew Bison 3.8.2 后重新生成 `loongarch-parse.c`，随后完成 `gmake` 和 `gmake install`。最终 `loongarch64-linux-gnu-as` 可用。

### 3. 普通交叉 GCC 基线

在 `build/gcc-normal` 构建 C/C++ compiler-only 工具链，启用 `--enable-checking=yes`，并用简单 C 函数生成 LoongArch64 汇编，确认“普通编译器 + binutils”基线可工作。先建立普通基线，再做插桩构建，降低了把交叉编译问题误认为 AFL++ 问题的风险。

### 4. 插桩构建中的问题与原因

早期尝试存在三类环境问题：

1. 当前交互 shell 是 fish，`set CC afl-clang-fast` 只创建 shell 变量，没有使用 `set -x` 导出，`configure` 子进程无法可靠继承。
2. 使用 `bash -c "..."` 包裹长命令时又嵌套双引号和命令替换，导致外层 fish 提前展开或截断变量，实际传给 `configure` 的内容与预期不一致。
3. 曾将安装目录变量命名为 `AFL_PREFIX`。这个名字本身是 AFL++ 的运行时环境变量，和“安装前缀”语义冲突，容易让 AFL wrapper 寻找错误的运行时位置。

最终处理方法是：

- 安装目录统一改用 `GCC_AFL_PREFIX`；
- 显式清理 `AFL_CC`、`AFL_CXX`、`AFL_PREFIX` 及遗留 flags；
- 在脚本中使用 AFL++、LLVM 和 binutils 的绝对路径；
- `CC/CXX` 只负责构建 GCC host 程序，分别指定为 `afl-clang-fast` 和 `afl-clang-fast++`；
- `CC_FOR_BUILD/CXX_FOR_BUILD` 指定普通 Clang，避免 build-machine 辅助程序被无意纳入 fuzz 目标；
- 使用独立的 `build/gcc-afl` 和 `install-afl`，不污染普通工具链。

### 5. 最终插桩配置

核心环境为：

```text
CC=/opt/homebrew/opt/afl++/bin/afl-clang-fast
CXX=/opt/homebrew/opt/afl++/bin/afl-clang-fast++
CC_FOR_BUILD=/opt/homebrew/opt/llvm/bin/clang
CXX_FOR_BUILD=/opt/homebrew/opt/llvm/bin/clang++
```

GCC 配置为：

```text
--target=loongarch64-linux-gnu
--prefix=/Users/mac/work/loong-gcc-afl/install-afl
--disable-bootstrap
--disable-multilib
--disable-nls
--enable-languages=c,c++
--without-headers
--disable-shared
--disable-threads
--disable-libatomic
--disable-libgomp
--disable-libquadmath
--disable-libssp
--disable-libsanitizer
--with-newlib
--enable-checking=yes
```

执行 `gmake -j8 all-gcc` 和 `gmake install-gcc` 后完成安装。构建期间 GCC C/C++ 自检累计通过约 765 万项检查。

## 四、插桩和运行验证结果

已安装的主要入口：

```text
/Users/mac/work/loong-gcc-afl/install-afl/bin/loongarch64-linux-gnu-gcc
/Users/mac/work/loong-gcc-afl/install-afl/bin/loongarch64-linux-gnu-g++
/Users/mac/work/loong-gcc-afl/install-afl/libexec/gcc/loongarch64-linux-gnu/17.0.0/cc1
/Users/mac/work/loong-gcc-afl/install-afl/libexec/gcc/loongarch64-linux-gnu/17.0.0/cc1plus
```

验证证据：

- `cc1` 中存在 `___afl_area_ptr`、`___afl_auto_init` 等 AFL++ runtime 符号；
- 不同 C 输入能生成非空且不同的 `afl-showmap` 覆盖图；
- 直接 fuzz `cc1` 时 AFL++ fork server 正常启动，目标 map size 为 1,529,271；
- GCC 的 `ICE_EXIT_CODE` 已从源码确认是 4，并通过 `AFL_CRASH_EXITCODE=4` 纳入故障归档。

2026-07-21 的 5 秒质量冒烟测试结果：

| 指标 | 结果 |
|---|---:|
| 执行次数 | 1,330 |
| 执行速度 | 265.20 次/秒 |
| 初始种子 | 2 |
| 新发现语料 | 183 |
| 最终语料数 | 185 |
| stability | 100.00% |
| bitmap coverage | 2.03% |
| 已发现边 / 可见总边 | 31,118 / 1,529,271 |
| ICE/崩溃 | 0 |
| 超时 | 0 |

结果目录为 `out/quality-smoke-20260721-083016/`。这证明构建、插桩、fork server、覆盖反馈、语料扩展和报告链路均已打通；5 秒结果仅用于工程冒烟，不代表已达到充分缺陷发现强度。

## 五、当前交付物

| 交付物 | 说明 |
|---|---|
| `scripts/build-gcc-afl.sh` | 重复构建和安装插桩 GCC，检查 Makefile 中的 AFL wrapper |
| `scripts/verify-gcc-afl.sh` | 静态符号、动态覆盖和短 fuzz 验证 |
| `scripts/afl-showmap-gcc.sh` | 单输入覆盖查看 wrapper |
| `scripts/afl-corpus-coverage.sh` | 语料累计覆盖、基线比较和最低阈值 |
| `scripts/run-gcc-afl-fuzz.sh` | 直接针对 `cc1/cc1plus` 的质量 fuzz 启动器 |
| `scripts/afl-coverage-report.sh` | 自动生成 Markdown 质量与覆盖报告 |
| `docs/AFL_GCC_CI_使用说明.md` | 操作手册和 CI 指标解释 |
| `seeds/`、`seeds-cxx/` | C 与 C++ 最小可运行种子 |

## 六、技术选择

1. **默认 fuzz `cc1/cc1plus`。** 减少 GCC driver 进程管理开销，避免 driver 和前端两层插桩覆盖混合，提高吞吐和指标可比性。
2. **把 ICE 退出码作为一等质量故障。** 语法错误不应被当成 crash；ICE 退出码 4 才进入 AFL crashes 队列。
3. **覆盖趋势和源码覆盖分开。** AFL bitmap/edge coverage 用于路径探索；若需要源码行和函数覆盖率，另建 gcov 流程。
4. **构建和运行环境显式化。** 不依赖 fish 会话中是否导出变量，保证 CI 可重复。
5. **LLM 不进入 AFL 高频执行热路径。** 远程模型响应慢、成本高且存在网络波动，不能每次执行都同步请求。

## 七、风险与限制

- 当前 GCC 是 experimental master 快照，行为会随上游提交变化；CI 报告必须记录 commit。
- 当前没有完整 sysroot，只覆盖编译前端、优化和汇编生成，不覆盖链接及目标运行时。
- 初始语料只有两个样例，语言特性和优化路径覆盖仍非常有限。
- macOS host 上个别单样例的 edge map 曾出现极少量条目漂移；应使用 stability 和带容差阈值，不以 map 逐字节一致为唯一判据。
- fuzz 发现的 crash 需要去重、最小化、确认可复现，并区分真实 GCC 缺陷与不支持配置。
- LLM 生成代码必须保留输入来源、prompt、模型版本和随机种子，才能审计和重放。

## 八、LLM 接入 AFL++ 的路线图

### 阶段 0：可重复基线（已完成主体）

目标：先建立无 LLM 的可靠比较基线。

- 固定 GCC commit、构建参数、AFL++ 版本和种子集；
- 将 C 与 C++、`-O0/-O2/-O3` 等任务拆成独立 CI job；
- 归档执行速度、稳定性、edge coverage、queue、crashes 和 hangs；
- 建立 ICE 最小化与回归入库规则。

完成标准：连续多次 CI 能稳定运行，覆盖阈值波动可解释，ICE 样例可自动留存。

### 阶段 1：高质量传统语料和字典

目标：在引入 LLM 前把低成本能力做扎实。

- 从 GCC testsuite 和团队已修复 bug 中抽取有许可、可维护的最小样例；
- 按 parser、template、constexpr、vector、attribute、builtin、optimizer 等特性分类；
- 建立 C/C++ token 字典和结构化片段库；
- 使用 `afl-cmin`/`afl-tmin` 或等价流程做覆盖去重和最小化；
- 建立合法输入率、编译阶段分布和单位时间新增边基线。

完成标准：种子规模可控，历史 ICE 全部可回归，传统 AFL 基线充分稳定。

2026-07-22 已在 `gcc-bugzilla-loongarch/` 建立 GCC Bugzilla 官方 REST 归档工具。初始高精度发现集约一百条，是因为只查询摘要和 Target 字段；扩展抓取加入公开评论全文与本地 LoongArch testsuite 的 PR 关联后，共发现 216 条候选，完整报告复核后保留 214 条，整理 448 个带来源和 SHA-256 的测试工件。严格 `llm-dataset.jsonl` 仍保持 61 条，扩展 `llm-expanded-dataset.jsonl` 增至 80 条，二者均要求明确 LoongArch64 证据、描述、测试材料且非 INVALID/MOVED，验证性提及不会进入 LLM 数据入口。

向量方向目前有 40 条报告在全文或测试材料中提到 LSX/LASX，其中 19 条在标题或 testcase 路径直接命中；严格集 25 条、扩展集 28 条。把一般 vectorization/SIMD 也纳入后，扩展集为 36 条。阶段 2 可先以这 36 条形成“LSX/LASX 专项 + 通用向量化”种子桶，分别生成 intrinsic、自动向量化、shuffle/permute、向量类型转换和寄存器约束类候选，再用插桩 `cc1/cc1plus` 做增量覆盖筛选。

### 阶段 2：LLM 离线语料生成

目标：最低工程风险地验证 LLM 是否带来增量覆盖。

- LLM 根据“未覆盖语言特性 + 现有最小样例”批量生成候选 C/C++ 文件；
- 本地先做大小限制、字符过滤、超时编译和语法/语义分类；
- 用 `afl-showmap` 只保留带来新边的样例；
- 对保留样例去重、最小化并写入带 provenance 的版本化 corpus；
- CI 默认使用缓存语料，不依赖在线模型服务。

完成标准：与传统种子相比，固定时间内 edge coverage 有可重复提升，且 CI 无网络依赖。

### 阶段 3：AFL++ custom mutator 原型

目标：让 LLM 或结构化生成器参与变异，同时不破坏 AFL 吞吐。

建议实现 AFL++ custom mutator API：

```text
afl_custom_init
afl_custom_fuzz
afl_custom_deinit
```

原型可先使用 AFL++ Python custom mutator 验证算法，再将高频结构化操作迁移到 C/C++ 动态库。mutator 的同步热路径只做毫秒级、本地、确定性的操作，例如：

- 根据轻量 AST/词法边界替换表达式、类型、属性和语句块；
- 拼接已验证的语言特性片段；
- 对常量、模板参数、向量宽度、循环结构做约束变异；
- 从 LLM 预生成池中取样，而不是现场调用远程模型。

### 阶段 4：异步 LLM 生产者架构

建议的数据流为：

```text
AFL queue / 低覆盖特征
        ↓
任务与样例选择器
        ↓
异步 LLM 生成服务（可选在线）
        ↓
本地校验、限长、编译与超时隔离
        ↓
showmap 增量覆盖筛选与去重
        ↓
有界候选池 / 版本化离线 corpus
        ↓
AFL custom mutator 高频消费
```

工程要求：

- 请求缓存、速率限制、失败重试和断网降级；
- prompt、模型、参数、父样例、输出 hash 和覆盖收益全链路记录；
- 候选池有容量上限和淘汰策略；
- 任何模型输出先经过本地资源限制，不能直接进入长期 CI corpus；
- 敏感源码只在公司批准的模型和数据边界内使用。

### 阶段 5：A/B 评估和 CI 产品化

在相同 CPU 时间、相同初始语料和相同 GCC commit 下比较：

| 指标 | 传统 AFL | AFL + 结构化 mutator | AFL + LLM 候选池 |
|---|---:|---:|---:|
| 新增边/小时 | 基线 | 对比 | 对比 |
| 有效编译输入率 | 基线 | 对比 | 对比 |
| 去重后 ICE 数 | 基线 | 对比 | 对比 |
| 执行吞吐下降 | 0 | 目标 < 10% | 目标 < 10% |
| 覆盖稳定性 | 基线 | 对比 | 对比 |
| 单个新增边成本 | 基线 | 对比 | 对比 |

只有在固定预算下持续获得显著新增边或独有 ICE，才将 LLM 模式进入正式周期性 CI。普通 PR 冒烟仍优先使用离线 corpus 和本地 mutator；夜间或周末任务可运行更长时间并刷新 LLM 候选池。

## 九、下一阶段建议排期

| 里程碑 | 建议周期 | 输出 |
|---|---:|---|
| M1：CI 基线固化 | 1 周 | C/C++ × 优化级别任务矩阵、覆盖阈值、产物归档 |
| M2：回归语料库 | 1～2 周 | testsuite/历史 bug corpus、分类字典、最小化流程 |
| M3：LLM 离线试验 | 1～2 周 | 生成与筛选流水线、provenance、A/B 数据 |
| M4：custom mutator 原型 | 2 周 | Python 原型、本地候选池、吞吐评估 |
| M5：工程化 | 2～4 周 | C/C++ mutator、异步服务、CI 分层策略和看板 |

## 十、ExtractLLM feature pool 当前进展

在历史 Bugzilla 语料归档基础上，已新增 `/Users/mac/work/loong-gcc-afl/extract-llm` 管线，用于把每条 bug report 整理成 ExtractLLM 可读输入，并使用真实 DeepSeek API 抽取结构化 feature。这里的 feature 定义为“自然语言描述的高层语义不变量 + 展示该语义如何实现的代码 witness”。一条 bug report 不被限制为一个 feature；如果同一报告中存在多个独立语义不变量、触发选项或 root-cause 关联，输出会以数组形式保留多个 feature，并在全局 `feature-pool.jsonl` 中展平成“一行一个 feature”。

本次实跑结果：

- 输入报告：214 条；
- 每条报告输出文件：214 个；
- 可抽取状态 `ok`：198 条；
- 证据不足 `insufficient_evidence`：16 条，主要是纯文档/脚本维护、外部工具链或不可转化为编译器测试的问题；
- `parse_error`：0 条，5 条模型 JSON 小破损已从 raw response 本地修复；
- `api_error`：0 条，尾段 11 条 `HTTP 402 Insufficient Balance` 已换 DeepSeek key 补跑完成；
- 当前 feature pool：926 个 feature；
- 多 feature 报告：178 条 bug report 产出了 2 个或更多 feature，单条报告最多 8 个 feature。

关键产物：

- `/Users/mac/work/loong-gcc-afl/extract-llm/out/extract-inputs.jsonl`：全部报告的 ExtractLLM 输入；
- `/Users/mac/work/loong-gcc-afl/extract-llm/out/features/bug-*.features.json`：每个 bug 的结构化抽取结果；
- `/Users/mac/work/loong-gcc-afl/extract-llm/out/feature-pool.jsonl`：后续 feature 组合和变异生成的主输入；
- `/Users/mac/work/loong-gcc-afl/extract-llm/out/feature-pool-manifest.json`：feature 数量、compiler area、failure mode、语言分布；
- `/Users/mac/work/loong-gcc-afl/extract-llm/README.md`：复现命令、质量边界和使用说明。

这一步把“历史 bug report + PoC + fix history”转成了可采样、可组合、可审计的语义 feature 池。下一步可以基于 feature pool 做离线组合生成：先按 compiler area、target option、failure mode 采样组合，再由 LLM/结构化生成器产出候选 C/C++ 测试，最后用当前 AFL showmap wrapper 做覆盖筛选，只有带来新增覆盖或触发 ICE 的样例进入 CI corpus。

## 十一、向管理层汇报的建议表述

当前已完成“可插桩、可反馈、可留存、可报告、可语义扩展”的阶段性闭环：LoongArch64 GCC 插桩构建成功，覆盖率反馈和 ICE 识别已验证，历史 Bugzilla 语料已归档，并已通过 ExtractLLM 形成 926 个可组合 feature。下一阶段的重点不是立即把 LLM 放进 fuzz 热路径，而是先用 feature pool 离线生成候选测试，通过覆盖增益和 ICE 发现率做 A/B 评估，最终以异步候选池加本地 custom mutator 的架构进入稳定 CI。
