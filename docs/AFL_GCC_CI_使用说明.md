# AFL++ 插桩 GCC 的质量测试与覆盖率使用说明

更新日期：2026-08-03

## 1. 测试范围

本项目是**编译器质量测试**，测试对象是团队自有 fork 的 GCC。输入是 C/C++ 源码样例，目标是持续发现和防止：

- internal compiler error（ICE）；
- 编译器进程崩溃；
- 异常长时间编译或死循环；
- 编译路径覆盖率下降；
- 已修复问题再次出现。

本项目不进行网络扫描、协议攻击、渗透测试，也不以第三方系统为目标。即使后续接入在线 LLM，LLM 也只负责生成编译器测试输入，不改变上述质量测试边界。

## 2. 已安装工具

工作根目录：`/Users/mac/work/loong-gcc-afl`

主要二进制：

```text
install-afl/bin/loongarch64-linux-gnu-gcc
install-afl/bin/loongarch64-linux-gnu-g++
install-afl/libexec/gcc/loongarch64-linux-gnu/17.0.0/cc1
install-afl/libexec/gcc/loongarch64-linux-gnu/17.0.0/cc1plus
```

日常 fuzz 和覆盖统计默认直接调用 `cc1` 或 `cc1plus`。GCC driver 会再启动前端子进程；若两者都带插桩，覆盖数据容易混合。直接调用前端更快，也更适合 CI 中做同口径比较。

### macOS AFL++ shared memory 配置

新机器首次运行 AFL++ 时，如果 `afl-showmap` 报：

```text
shmget() failed, try running afl-system-config
```

需要先调大 macOS 的 SysV shared memory 参数。直接执行：

```bash
sudo /opt/homebrew/opt/afl++/bin/afl-system-config
```

也可以手动执行等价的关键配置：

```bash
sudo sysctl -w kern.sysv.shmmax=524288000
sudo sysctl -w kern.sysv.shmall=131072000
sudo sysctl -w kern.sysv.shmseg=48
```

本项目的插桩 `cc1` 当前需要的 AFL map 大小约为 `4248342` 字节。若 `kern.sysv.shmmax` 仍是 macOS 默认的 `4194304`，`afl-showmap` 会在启动 shared memory 时失败。配置后可用以下命令确认：

```bash
sysctl kern.sysv.shmmax kern.sysv.shmall kern.sysv.shmseg
```

这些配置属于本机运行环境，重启后可能需要重新执行。

## 3. 单个样例查看覆盖率

在工作根目录执行：

```bash
cd /Users/mac/work/loong-gcc-afl
./scripts/afl-showmap-gcc.sh seeds/minimal.c
```

脚本会显示目标前端、输入文件、edge map 条目数及 `.map` 文件位置。默认输出在 `out/showmap/`。

测试 C++：

```bash
./scripts/afl-showmap-gcc.sh --lang c++ path/to/test.cc
```

带编译选项并指定输出：

```bash
./scripts/afl-showmap-gcc.sh \
  --output out/showmap/test-o2.map \
  path/to/test.c -- -O2 -Wall
```

只有在排查 GCC driver 行为时才使用：

```bash
./scripts/afl-showmap-gcc.sh --mode driver path/to/test.c
```

## 4. 查看整个语料库的累计覆盖

```bash
./scripts/afl-corpus-coverage.sh seeds
```

脚本用 `afl-showmap -C` 回放目录中的全部样例，输出累计 edge map。若目录名是 AFL 的 `queue`，脚本只回放 `id:*` 文件，避免把状态文件当成 C 源码。

建立一条固定构建、固定参数的覆盖基线：

```bash
./scripts/afl-corpus-coverage.sh \
  --output baselines/cc1-c-default.map \
  seeds
```

与基线比较，并设置 CI 最低条目数：

```bash
./scripts/afl-corpus-coverage.sh \
  --baseline baselines/cc1-c-default.map \
  --min-edges 27000 \
  --output out/ci-current.map \
  seeds
```

`--min-edges` 未达到时退出码为 3，可直接让 CI job 失败。阈值必须在同一 GCC 构建方式、同一 `cc1/cc1plus`、同一参数和同一语料集下制定。

## 5. 启动质量 fuzz 测试

60 秒 C 前端冒烟测试：

```bash
./scripts/run-gcc-afl-fuzz.sh \
  --seconds 60 \
  --output out/ci-smoke \
  seeds
```

测试优化路径：

```bash
./scripts/run-gcc-afl-fuzz.sh \
  --seconds 600 \
  --output out/ci-o2 \
  seeds -- -O2
```

测试 C++：

```bash
./scripts/run-gcc-afl-fuzz.sh \
  --lang c++ \
  --seconds 600 \
  --output out/ci-cxx \
  seeds-cxx
```

省略 `--seconds` 会持续运行，按 `Ctrl-C` 正常停止。输出目录必须是新目录，避免覆盖已有结果。

脚本设置 `AFL_CRASH_EXITCODE=4`。GCC 源码的 `gcc/system.h` 将 `ICE_EXIT_CODE` 定义为 4，因此 AFL++ 会把正常语法错误（通常退出码 1）与 ICE 区分开，并把 ICE 输入保存到 `default/crashes/`。

## 6. 生成和阅读覆盖报告

对一次 AFL 输出生成 Markdown 报告，同时重放 queue 计算累计覆盖：

```bash
./scripts/afl-coverage-report.sh out/ci-smoke
```

如果 fuzz 时给前端传了选项，重放覆盖时必须使用相同选项，例如：

```bash
./scripts/afl-coverage-report.sh out/ci-o2 -- -O2
```

结果写入：

```text
out/ci-smoke/coverage-report.md
out/ci-smoke/queue-coverage-c.map
```

若只想快速读取 `fuzzer_stats`，不重放语料：

```bash
./scripts/afl-coverage-report.sh --no-recalculate out/ci-smoke
```

在 CI 中让 ICE/崩溃或超时自动返回非零退出码：

```bash
./scripts/afl-coverage-report.sh --ci out/ci-smoke
```

关键指标的含义：

| 指标 | 质量测试含义 |
|---|---|
| `edges_found / total_edges` | 当前语料触达的插桩控制流边与目标可见边总数 |
| `bitmap_cvg` | AFL bitmap 占用比例，适合相同配置下比较趋势 |
| `stability` | 同一样例重复执行时覆盖是否一致；越接近 100% 越好 |
| `execs_per_sec` | 测试吞吐量，评估 CI 时长和 mutator 开销 |
| `corpus_found` | fuzz 过程中新增的有价值语料数 |
| `saved_crashes` | ICE（退出码 4）或进程崩溃样例数 |
| `saved_hangs` | 超时样例数，需要区分真实性能回归和阈值过紧 |

注意：AFL 的控制流边覆盖率不是 `gcov` 的源码行覆盖率。前者用于引导 fuzz 和衡量路径探索；若领导或质量体系要求“源码行/函数覆盖率”，使用 `scripts/build-gcc-gcov.sh` 和 `scripts/gcc-source-coverage-replay.py` 生成 gcov 口径报告，两种指标并列呈现，不应互相替代。

## 7. 建议的 CI 判定规则

短期可采用以下门禁：

1. 构建插桩版 `cc1/cc1plus`，检查二进制包含 `___afl_area_ptr`。
2. 固定语料运行 1～10 分钟冒烟 fuzz。
3. `saved_crashes > 0` 时失败，并归档 `crashes/`。
4. `saved_hangs > 0` 时先失败，再人工确认是否为性能回归。
5. 累计 edge map 条目数低于固定阈值时失败。
6. 归档 `fuzzer_stats`、`queue/`、`crashes/`、`hangs/`、`.map` 和 `coverage-report.md`。
7. 对有效 ICE 做样例最小化，并加入长期回归语料库。

在当前 macOS 主机上，单样例重复运行曾观察到极少量 edge map 条目漂移；累计条目总数相对稳定，实测短跑 `stability` 为 100%。因此 CI 应优先使用稳定性指标和带容差的覆盖阈值，不建议仅因两个 `.map` 文件未逐字节完全相同就判失败。

## 8. 脚本清单

| 脚本 | 用途 |
|---|---|
| `scripts/build-gcc-afl.sh` | 可重复构建并安装插桩 GCC |
| `scripts/verify-gcc-afl.sh` | 插桩符号、动态覆盖和短时 fuzz 一体化验证 |
| `scripts/afl-showmap-gcc.sh` | 查看单个编译样例的控制流边覆盖 |
| `scripts/afl-corpus-coverage.sh` | 聚合语料覆盖、对比基线和设置 CI 下限 |
| `scripts/run-gcc-afl-fuzz.sh` | 以质量测试模式启动 cc1/cc1plus fuzz |
| `scripts/afl-coverage-report.sh` | 从 AFL 结果生成 Markdown 质量报告 |
