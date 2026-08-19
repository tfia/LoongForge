# LoongArch64 GCC 插桩质量测试工作纪要与 LLM 变异路线图

汇报日期：2026-08-12
工作目录：`/Users/mac/work/loong-gcc-afl`

仓库名：`loongforge`。当前已将上述工作目录初始化为单仓库 monorepo，但保留原目录名，避免破坏已有脚本和历史报告中的绝对路径。GCC 和 binutils-gdb 源码不直接提交到 monorepo，而是以 `src/gcc-upstream`、`src/binutils-gdb` 两个 Git submodule 锁定版本；具体 commit 见顶层 `third_party/SOURCES.lock`。构建目录、安装目录、AFL 输出、LLM raw outputs 和 `.env` 均由 `.gitignore` 排除，只有代码、文档、脚本、种子和 curated 状态快照进入版本管理。

当前 LLM 管线已扩展为 ExtractLLM -> GroupLLM -> InstanLLM。新增 `instan-llm/` 模块负责读取 GroupLLM 的 ready feature groups，生成完整编译器测试程序，并用 AFL++ wrapped GCC 前端编译记录 edge coverage。只有成功产生非空 coverage map 的 C/C++ 程序会进入 `instan-llm/out/corpus/covered/`，作为后续 CI corpus 候选。

2026-08-05 阶段验证结果：对当前 evaluator 可直接处理的全部 272 个 C/C++ GroupLLM ready groups 做真实 LLM API 测试。InstanLLM 生成 260 个 ready 程序，10 个 rejected，2 个持续 API/parser error；260 个 ready 程序均通过 AFL++ wrapped GCC 覆盖评估并产生非空 edge map。该批 mixed-optimization union edge 为 261,917，单测例 edge map 条目范围为 2631 到 101423，平均 20319.6。阶段覆盖报告已写入 `docs/InstanLLM_阶段覆盖率报告.md`。

随后已单独构建 gcov 口径 GCC，并用同一批 260 个 covered corpus 重放，开始回答“覆盖了多少 GCC 源码行/函数”的质量汇报问题。当前源码覆盖口径只统计真实存在于 `src/gcc-upstream` 下的 GCC 源码文件，不把测试程序、系统头文件或 build 目录生成文件计入分母；结果为源码行覆盖 298,606/909,439（32.83%）、函数覆盖 38,216/95,267（40.11%）、分支覆盖 224,427/828,708（27.08%）。260 条测例均已执行，其中 104 条返回 0、156 条非零退出；非零退出多来自缺少外部头文件或负向测试，但仍会覆盖 GCC 前端、诊断和 include 搜索路径，因此保留在质量测试覆盖口径中。

2026-08-06 至 2026-08-12 已接入并迭代论文式 AFL edge 反馈闭环：GroupLLM 可读取 InstanLLM 的 AFL maps，计算每个 group 对 union edge 的新增贡献，并把 reward 分配给 source features，用于下一轮 feature 选取和组合。reward 不是硬规则，而是覆盖反馈排序信号：`reward_score = new_edges_sum + 25.0 * novel_group_count + 0.001 * edge_entries_sum`。架构、ABI、优化选项、测试模式和 harness 能力仍是 hard gate，reward 再高也不能绕过。第一版全局 reward 加权导致跨 target/language/test-mode 混组，真实小批 rejected 率为 91.67%；加入 LoongArch C/C++ AFL harness 兼容池、required target arch hard gate 和 test-mode hard gate 后，真实小批 rejected 率降到 25.00%。修复后的 9 个新 ready groups 经 InstanLLM 全部生成 ready 且 AFL covered，将 covered corpus 从 260 扩到 269，mixed-optimization union edge 从 261,917 提升到 263,073（+1,156）。阶段评估见 `docs/AFL反馈闭环阶段评估.md`。

2026-08-12 根据领导建议，InstanLLM evaluation 默认切换为 `-Ofast`：评估前清理原有 `-O*` 并在 compiler options 前置 `-Ofast`，以更集中地触发优化器、向量化、combine、RTL expand/split 等高风险路径。当前 `-Ofast` 统一重放 269 个 covered corpus，AFL union edge 基线为 260,124；该数值与历史 mixed-optimization 263,073 属于不同编译选项口径，后续趋势比较应固定在 `-Ofast` 口径。当前没有 ICE：`ice=0`。如果后续出现 ICE-like crash，必须先复现并对比已有 bug PoC、`source_bug_ids` 和 stderr signature，区分“老问题被重新覆盖”和“新问题候选”。

2026-08-12 还新增并修复了 `scripts/run-afl-feedback-loop.py` 长程运行器，用于按轮次执行 `prepare -> GroupLLM -> build-groups -> InstanLLM -> AFL evaluate -> feedback`，并提供分组日志、独立超时和可恢复能力。该脚本不新增管线模式，只是把现有命令编排成适合夜间/周末正式测试的任务。长程调试中发现两个工程问题并已修复：一是 reasoning-style provider 容易把 token 用在 `reasoning_content` 导致 `message.content` 空，已通过缩短 witness、提高 `max_tokens`、约束直接输出 JSON 缓解；二是 InstanLLM 原先批量提交 40+ groups 时容易被外层 timeout 截断，已改为逐 group 独立超时。

2026-08-12 已完成两轮有效大批量 `-Ofast` feedback loop：covered corpus 从 269 增至 345，AFL union edge 从 260,124 增至 288,889，累计新增 28,765 edges（+11.06%），未发现 ICE。2026-08-13 更换 provider 后提高并发继续执行 3 个大轮次：GroupLLM 并发从 4 提到 6，InstanLLM 并发从 2 提到 4，并把 process timeout 放宽到 720 秒；第 1 并发轮的 timeout 已补跑成功。三轮新增 covered 126 个，AFL union edge 从 288,889 提升到 299,954，新增 11,065 edges；相对 `-Ofast` 初始基线累计新增 39,830 edges（+15.31%）。三轮均未发现 ICE-like crash（`ice=0`）。并发优化后三轮含补跑总 wall time 约 3.04 小时，单轮约 0.95-1.08 小时，较此前 2.4-2.6 小时/轮明显提速；edge 增长依次为 +7,292、+2,228、+1,545，显示覆盖进入边际递减区间。

2026-08-19 进一步给长程 runner 增加 AFL++ 原生变异开关：默认仍是原来的 showmap-only 反馈闭环；传 `--native-afl-seconds N` 后，每轮在 InstanLLM evaluate 后把本轮 covered 程序作为 seed corpus，调用原生 `afl-fuzz` 运行 N 秒，再用 `afl-showmap` 重放 AFL queue 并把 queue-level edge map 合入 GroupLLM feedback。InstanLLM showmap 仍提供 per-group reward；native AFL queue map 属于 batch-level reward，新增 edge 平均分给本轮 seed batch 的 source features。推荐较快大轮次命令使用 GroupLLM 并发 6、InstanLLM 并发 4，并把 native AFL 先设为每轮 180 秒：

```bash
cd /Users/mac/work/loong-gcc-afl
scripts/run-afl-feedback-loop.py \
  --iterations 2 \
  --batch-size 48 \
  --group-parallel 6 \
  --group-api-timeout 180 \
  --group-process-timeout 720 \
  --instan-workers 4 \
  --instan-process-timeout 720 \
  --instan-timeout 180 \
  --evaluate-timeout-ms 30000 \
  --optimization=-Ofast \
  --coverage-basis ready \
  --native-afl-seconds 180 \
  --native-afl-languages c \
  --native-afl-timeout 5000+
```

同日已完成 2 轮 native AFL enabled 大闭环实测，日志目录为 `logs/afl-feedback-loop/20260819-163452`。在当前 provider 状态下，GroupLLM 并发 6 出现较多读超时：两轮 96 个 candidates 中 only 23 ready，65 个 `api_error` 均为 `DeepSeek request failed: The read operation timed out`。尽管 ready 率偏低，13 个 covered seed 加上每轮 180 秒 native AFL 仍把 AFL union edge 从 299,954 提升到 307,099，新增 +7,145；其中 native AFL queue map 贡献约 +6,043，InstanLLM showmap per-group 贡献约 +1,135。两轮 native AFL queue inputs 分别为 1,336 和 1,437，crashes/hangs 均为 0，ICE=0。结论：原生 AFL 变异阶段已经有效打通并显著提高 edge 增长，但下一轮若要提高端到端效率，应优先降低 GroupLLM 并发到 3-4 或提高 `--group-api-timeout`/`--group-retries`，避免 provider 超时吞掉候选。

InstanLLM 后续 roadmap：

1. 固化 AFL feedback-guided C/C++ 迭代：保留当前 471 个 covered 程序作为 CI corpus 候选，并继续以新增 union edge 作为入库优先级。
2. 下一次长程任务不要无限跑；建议每次 1-3 个大轮次为单位执行，记录 AFL union edge 增长率、API/parser error、GroupLLM rejected 率、InstanLLM timeout 和 ICE-like crash。
3. 增强 oracle：区分 `compile_success`、`compile_failure`、`assembly_scan`、`runtime_exit` 和 `differential`，避免所有测试只按“能编译并有 edge”判定。
4. 继续降低 GroupLLM rejected 率：把 rejected 原因沉淀成本地 required target arch、test-mode、frontend/harness hard gate，减少无效 LLM 调用。
5. 接入 corpus admission：只把 covered 且 oracle 合格、或能带来新增 union edge 的程序加入 CI corpus，重复覆盖样例降级为备选语料。
6. 补齐专用 harness：为 assembly-scan、diagnostic、Fortran、asm、RTL、Ada/D/COBOL/shell 分别实现 evaluator。当前这些 GroupLLM ready groups 不是无效，而是不能直接用 `cc1/cc1plus` wrapper 评价。
7. 保留 gcov 源码覆盖重放作为质量汇报口径；短期不继续扩展，优先完善 AFL feedback 闭环。

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
| `scripts/build-gcc-gcov.sh` | 构建 gcov 口径 GCC，用于源码行/函数覆盖统计 |
| `scripts/gcc-source-coverage-replay.py` | 用 InstanLLM covered corpus 重放 coverage GCC 并生成源码覆盖报告 |
| `docs/AFL_GCC_CI_使用说明.md` | 操作手册和 CI 指标解释 |
| `docs/GCC源码覆盖率使用说明.md` | gcov 源码覆盖率构建、重放和汇报口径说明 |
| `seeds/`、`seeds-cxx/` | C 与 C++ 最小可运行种子 |

## 六、技术选择

1. **默认 fuzz `cc1/cc1plus`。** 减少 GCC driver 进程管理开销，避免 driver 和前端两层插桩覆盖混合，提高吞吐和指标可比性。
2. **把 ICE 退出码作为一等质量故障。** 语法错误不应被当成 crash；ICE 退出码 4 才进入 AFL crashes 队列。
3. **覆盖趋势和源码覆盖分开。** AFL bitmap/edge coverage 用于路径探索和入库筛选；gcov 源码行/函数覆盖用于质量汇报和 CI 趋势，两者并列呈现。
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


2026-08-19 根据领导关于“通用 GCC bug 是否更适合提炼高质量 feature”的问题，爬虫设计扩展为双模式：默认 `loongarch` 模式保持现有 LoongArch 专项口径；新增 `general-quality` 模式按 ICE、wrong-code/miscompilation、missed optimization、reduced testcase、preprocessed source、命令行、regression 和 compiler component 等信号，从 GCC Bugzilla 中抽样抓取通用高质量 bug。通用数据单独输出到 `llm-general-ready.jsonl` 和 `llm-general-dataset.jsonl`，不会污染 LoongArch 专用数据集。

通用 Bugzilla 抓取比 LoongArch 专项抓取慢很多是符合预期的：LoongArch 模式搜索范围窄，候选少；通用模式要对 GCC 产品的摘要和公开评论全文做多条 discovery query，并且每个候选还要补抓 comments、attachments 和 testcase。首次真实尝试中，过于保守的 `--delay 30.0` 会把 40 条归档拖到数小时量级；同时如果不限制创建时间，全文搜索会纳入很早创建、后来又被更新的历史 bug，例如编号很小但 `last_change_time` 很新的报告。为此爬虫新增 `--general-created-after`，首批真实归档推荐只采样较新的 bug：

```bash
cd /Users/mac/work/loong-gcc-afl/gcc-bugzilla-loongarch
uv run loongarch-bug-corpus sync \
  --scope general-quality \
  --archive-dir archive-general-quality \
  --general-created-after 2020-01-01 \
  --general-query-limit 80 \
  --general-quality-min-score 6 \
  --limit 40 \
  --delay 5.0 \
  --timeout 180 \
  --retries 6 \
  --retry-max-delay 90
uv run loongarch-bug-corpus verify --archive-dir archive-general-quality
```

如果这组参数仍遇到 GCC Bugzilla 429，再把 `--delay` 调到 `8.0` 或 `10.0`；不要一开始使用 30 秒级 delay。建议每批 40 到 80 条，分批观察 `general_quality_score`、testcase 数量、ExtractLLM parser/error 率和后续 AFL edge 增益，再决定是否扩量。

这一步把“历史 bug report + PoC + fix history”转成了可采样、可组合、可审计的语义 feature 池。下一步可以基于 feature pool 做离线组合生成：先按 compiler area、target option、failure mode 采样组合，再由 LLM/结构化生成器产出候选 C/C++ 测试，最后用当前 AFL showmap wrapper 做覆盖筛选，只有带来新增覆盖或触发 ICE 的样例进入 CI corpus。

## 十一、向管理层汇报的建议表述

当前已完成“可插桩、可反馈、可留存、可报告、可语义扩展”的阶段性闭环：LoongArch64 GCC 插桩构建成功，覆盖率反馈和 ICE 识别已验证，历史 Bugzilla 语料已归档，并已通过 ExtractLLM 形成 926 个可组合 feature。当前系统已经能把 AFL 新增 edge 转换为 feature reward，反馈到 GroupLLM 的下一轮组合；InstanLLM 评估已切到 `-Ofast`，用于更集中地测试优化器高风险路径。五轮正式大批量迭代把 covered corpus 从 269 扩到 471，把 `-Ofast` AFL union edge 从 260,124 提升到 299,954（+15.31%），说明该闭环已经能稳定带来覆盖增长；其中 08-13 并发三轮把单轮耗时降到约 1 小时。下一阶段重点是提升 oracle、修复 not-ready/rejected、补齐专用 harness 和 corpus admission；如果出现 ICE-like crash，再按已制定的 signature/PoC 去重复核流程确认是否为新问题。
