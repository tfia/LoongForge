# GCC 源码覆盖率报告

生成时间：`2026-08-05T16:57:22Z`

测试范围：自有 LoongArch GCC fork 的编译器 CI 质量测试；不涉及网络安全测试。

## 汇总

| 指标 | 数值 |
| --- | --- |
| 重放测例数 | 260 |
| 重放返回 0 | 104 |
| 重放非零退出 | 156 |
| 重放超时 | 0 |
| GCC 源码文件数 | 1583 |
| 源码行覆盖 | 298,606/909,439 (32.83%) |
| 函数覆盖 | 38,216/95,267 (40.11%) |
| 分支覆盖 | 224,427/828,708 (27.08%) |

## 口径说明

- 本报告使用 gcov 读取 coverage 版 GCC 运行后生成的 `.gcda/.gcno`，统计 GCC 源码树内文件的源码行、函数和分支覆盖。
- 它回答的是“这批编译器测试让 GCC 自身源码执行了多少行/函数”，不是 AFL edge map；两者应并列使用。
- 只统计真实存在于 `src/gcc-upstream` 下的文件；测试程序、系统头文件和 GCC build 目录生成文件不计入分母。
- 当前重放以 `-S` 编译到汇编，避免链接/sysroot 依赖；因此覆盖重点是 driver、C/C++ 前端、优化器和 LoongArch 后端编译路径。
- 非零退出的测例仍会触发 GCC 前端/诊断路径并产生 coverage，因此保留在质量测试口径中；返回 0 单独列出用于说明语料可编译比例。

## 结果解读

- 260 条 InstanLLM covered corpus 已能覆盖约三分之一 GCC 源码可统计行和约四成函数，说明当前 LLM 生成 corpus 不只是停留在 driver 层，已经进入前端、优化器和后端主要编译路径。
- 覆盖最多的文件集中在 C/C++ parser/type checking、GIMPLE/RTL 优化、寄存器分配，以及 `gcc/config/loongarch`。其中 `gcc/config/loongarch/loongarch.cc` 覆盖 3,346/5,285 行、277/314 个函数，`gcc/config/loongarch/loongarch.md` 覆盖 1,598/2,776 行、171/356 个函数，说明语料确实触达 LoongArch 后端和机器描述路径。
- 当前 104/260 返回 0，非零退出的常见原因是生成程序引用了 compiler-only sysroot 不具备的外部头文件，例如 `ffi.h`。这些执行仍对诊断和 include 搜索路径有质量测试价值，但下一步应通过 prompt 约束或最小测试 sysroot 提升可编译比例。

## 覆盖最多的源码文件 Top 20

| 文件 | 覆盖行 | 总行 | 行覆盖率 | 覆盖函数 | 总函数 | 函数覆盖率 |
| --- | --- | --- | --- | --- | --- | --- |
| `gcc/cp/parser.cc` | 5573 | 25144 | 22.16% | 322 | 757 | 42.54% |
| `gcc/combine.cc` | 4731 | 6811 | 69.46% | 98 | 107 | 91.59% |
| `gcc/fold-const.cc` | 4101 | 8558 | 47.92% | 160 | 224 | 71.43% |
| `gcc/tree.cc` | 4099 | 7447 | 55.04% | 332 | 459 | 72.33% |
| `gcc/tree-vect-slp.cc` | 3817 | 6034 | 63.26% | 169 | 197 | 85.79% |
| `gcc/dwarf2out.cc` | 3675 | 14641 | 25.10% | 312 | 635 | 49.13% |
| `gcc/c/c-typeck.cc` | 3629 | 9435 | 38.46% | 140 | 209 | 66.99% |
| `gcc/tree-ssa-sccvn.cc` | 3547 | 4675 | 75.87% | 133 | 140 | 95.00% |
| `gcc/c/c-parser.cc` | 3536 | 16112 | 21.95% | 130 | 358 | 36.31% |
| `gcc/config/loongarch/loongarch.cc` | 3346 | 5285 | 63.31% | 277 | 314 | 88.22% |
| `gcc/cp/decl.cc` | 3208 | 9912 | 32.36% | 133 | 245 | 54.29% |
| `gcc/c/c-decl.cc` | 3027 | 6368 | 47.53% | 117 | 188 | 62.23% |
| `gcc/gimplify.cc` | 2786 | 10977 | 25.38% | 118 | 246 | 47.97% |
| `gcc/tree-vect-stmts.cc` | 2778 | 7199 | 38.59% | 71 | 108 | 65.74% |
| `gcc/expr.cc` | 2768 | 6781 | 40.82% | 115 | 186 | 61.83% |
| `gcc/simplify-rtx.cc` | 2705 | 5164 | 52.38% | 58 | 82 | 70.73% |
| `gcc/tree-cfg.cc` | 2625 | 5099 | 51.48% | 148 | 214 | 69.16% |
| `gcc/tree-ssa-loop-ivopts.cc` | 2621 | 3624 | 72.32% | 171 | 189 | 90.48% |
| `gcc/var-tracking.cc` | 2582 | 4703 | 54.90% | 157 | 196 | 80.10% |
| `gcc/tree-vect-loop.cc` | 2531 | 5242 | 48.28% | 60 | 101 | 59.41% |

完整机器可读结果在本地 `out/source-coverage/instanllm-covered/` 下，包括 `gcc-source-coverage-summary.json`、`per-file-coverage.json` 和 `replay-results.json`。该目录不进入 git，用于本机复查和 CI artifact 归档。
