# GCC 源码覆盖率使用说明

本文说明如何用当前 InstanLLM covered corpus 回放 coverage 版 GCC，回答“这批测试覆盖了多少 GCC 源码行/函数”。

这是编译器 CI 质量测试，不是网络安全测试。AFL edge map 和 gcov 源码覆盖率是两套指标：

- AFL edge map：用于 fuzz/corpus admission，衡量插桩 GCC 前端执行路径是否增加。
- gcov 源码覆盖率：用于质量汇报，衡量 GCC 源码树内行、函数、分支被执行了多少。

## 1. 构建 gcov 口径 GCC

```bash
cd /Users/mac/work/loong-gcc-afl
./scripts/build-gcc-gcov.sh
```

默认输出：

- 构建目录：`/Users/mac/work/loong-gcc-afl/build/gcc-gcov`
- 安装目录：`/Users/mac/work/loong-gcc-afl/install-gcov`
- 目标三元组：`loongarch64-linux-gnu`

默认使用 Homebrew `gcc-15/g++-15/gcov-15`。如需覆盖：

```bash
GCOV_CC=/opt/homebrew/bin/gcc-15 \
GCOV_CXX=/opt/homebrew/bin/g++-15 \
JOBS=10 \
./scripts/build-gcc-gcov.sh
```

## 2. 重放当前 InstanLLM covered corpus

```bash
cd /Users/mac/work/loong-gcc-afl
./scripts/gcc-source-coverage-replay.py
```

脚本读取：

- `instan-llm/out/evaluations.jsonl`
- 其中 `evaluation_status == covered` 的 C/C++ 测例
- 每条评估记录中的 `source_path` 和 `compiler_options`

脚本会：

1. 清理 `build/gcc-gcov` 下旧 `.gcda`；
2. 用 `install-gcov/bin/loongarch64-linux-gnu-gcc/g++` 对 covered 测例执行 `-S` 编译重放；
3. 调用 `gcov-15` 解析 `.gcda/.gcno`；
4. 输出源码行、函数、分支覆盖率。

默认报告：

- `out/source-coverage/instanllm-covered/gcc-source-coverage-report.md`
- `out/source-coverage/instanllm-covered/gcc-source-coverage-summary.json`
- `out/source-coverage/instanllm-covered/per-file-coverage.json`

可提交/汇报的当前快照：

- `docs/GCC源码覆盖率报告.md`

当前 2026-08-05 的完整重放结果：

- 重放测例数：260
- 重放返回 0：104
- 重放非零退出：156
- GCC 源码文件数：1583
- 源码行覆盖：298,606/909,439（32.83%）
- 函数覆盖：38,216/95,267（40.11%）
- 分支覆盖：224,427/828,708（27.08%）

非零退出不等同于脚本失败。很多 generated corpus 是负向测试或包含当前 compiler-only sysroot 不具备的外部头文件；这类执行仍会覆盖 GCC driver、前端、诊断和 include 搜索路径，因此保留在质量测试覆盖口径中。返回 0 用于说明 corpus 可编译比例。

## 3. 常用调试命令

先用小批量验证构建是否可用：

```bash
./scripts/gcc-source-coverage-replay.py --limit 5
```

不清理旧 `.gcda`，做增量累计：

```bash
./scripts/gcc-source-coverage-replay.py --no-reset
```

指定输出目录：

```bash
./scripts/gcc-source-coverage-replay.py \
  --out-dir /Users/mac/work/loong-gcc-afl/out/source-coverage/manual-run
```

## 4. 汇报口径

对领导或 CI 报告建议同时给出：

- AFL union edge：回答“测试是否探索了更多编译器执行路径”；
- gcov line coverage：回答“覆盖了 GCC 源码多少行”；
- gcov function coverage：回答“覆盖了 GCC 源码多少函数”；
- replay 成功率：说明源码覆盖统计是否基于完整 corpus。

如果 replay 失败率升高，优先检查是否有测例依赖链接、系统头文件或当前 cross GCC 不支持的参数。

当前第一轮结果显示，下一步最直接的提升点是降低外部头文件依赖导致的非零退出比例，例如在 InstanLLM prompt 中约束只使用内建类型/标准语法，或在专门的 compiler-only sysroot 中补齐质量测试所需的最小头文件集合。
