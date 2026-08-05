# InstanLLM 阶段覆盖率报告

生成时间：`2026-08-05T09:55:08Z`

测试范围：自有 LoongArch GCC fork 的编译器 CI 质量测试；不涉及网络安全测试。

## 本轮结论

| 指标 | 数值 |
| --- | --- |
| GroupLLM ready groups 总数 | 289 |
| 当前 evaluator 可直接处理的 C/C++ ready groups | 272 |
| 其他语言/专用 harness backlog | 17 |
| 本轮选择的 groups | 24 |
| InstanLLM ready | 24 |
| AFL++ covered | 24 |
| 本轮 InstanLLM ready 率 | 100.00% |
| 本轮 AFL covered 率 | 100.00% |
| 本轮覆盖 GroupLLM ready 比例 | 8.30% |
| 本轮覆盖 C/C++ ready 比例 | 8.82% |

## AFL edge map 统计

| 指标 | 数值 |
| --- | --- |
| covered programs | 24 |
| 最小 edge map 条目 | 2631 |
| 最大 edge map 条目 | 84303 |
| 平均 edge map 条目 | 17002.2 |
| 中位 edge map 条目 | 3402.0 |

这些 edge map 条目来自 AFL++ instrumentation，不是 gcov 源码行覆盖率。它用于比较同一 wrapped GCC、同一前端和同一编译参数口径下的编译器路径覆盖趋势。

## 语言与 oracle 分布

| 语言 | GroupLLM ready | 本轮 InstanLLM |
| --- | --- | --- |
| ada | 1 | 0 |
| asm | 5 | 0 |
| c | 243 | 23 |
| c++ | 29 | 1 |
| cobol | 1 | 0 |
| d | 2 | 0 |
| fortran | 6 | 0 |
| shell | 2 | 0 |

| oracle kind | 数量 |
| --- | --- |
| assembly_scan | 3 |
| compile_failure | 1 |
| compile_success | 7 |
| differential | 1 |
| runtime_exit | 12 |

## 本轮程序明细

| candidate | language | status | edge entries | source |
| --- | --- | --- | --- | --- |
| group-0001-0c4805f873ab | c | covered | 3390 | lasx_shuffle_xvldx_test.c |
| group-0003-0913e3e3f3bd | c | covered | 3360 | loongarch_ice_combined.c |
| group-0004-827806713198 | c | covered | 48203 | sibcall_abi_padding_test.c |
| group-0008-9b3ffea126fb | c | covered | 10974 | loongarch_combined_bugs.c |
| group-0009-de11becdf0ee | c++ | covered | 3426 | loongarch_ice_test.cc |
| group-0010-92fb7029d82a | c | covered | 3374 | loongarch_vector_round_shuffle_pick.c |
| group-0011-9268b3400021 | c | covered | 3390 | loongarch_combined.c |
| group-0013-21f2fcd244d0 | c | covered | 17238 | loongarch_vec_test.c |
| group-0014-eb55f2204699 | c | covered | 40267 | test_128bit_shift_large_const.c |
| group-0015-eed89675e7a2 | c | covered | 3403 | loongarch_vector_rounding.c |
| group-0016-fed9b0650eb5 | c | covered | 18518 | group_0016_test.c |
| group-0017-1534392225bf | c | covered | 50780 | test_group_0017.c |
| group-0018-ee210b474afe | c | covered | 44040 | loongarch_ice_combine.c |
| group-0023-f6851481d876 | c | covered | 3365 | test_lasx_simd.c |
| group-0024-1e4e0ae3bdf8 | c | covered | 3416 | lsx_combined_test.c |
| group-0026-677adba21106 | c | covered | 2631 | loongarch_ice_triggers.c |
| group-0028-2c0c7a7b367e | c | covered | 84303 | test_loongarch_opt.c |
| group-0030-30491d959663 | c | covered | 3379 | vector_shuffle_abi.c |
| group-0032-1c4e8fe9e883 | c | covered | 3392 | loongarch_inline_lsx_fp_test.c |
| group-0034-dae0859c28a0 | c | covered | 3390 | loongarch_vec_ice_combined.c |
| group-0036-0e72d2cc9821 | c | covered | 3385 | loongarch_multi_bug_test.c |
| group-0039-99e7421fda60 | c | covered | 3401 | lsx_vector_ice_test.c |
| group-0041-e097040f4fb4 | c | covered | 43645 | loongarch_combined_test.c |
| group-0045-6d124569400f | c | covered | 3384 | loongarch_switch_vector_bitclear_pic.c |

## 当前边界与后续工作

- 当前 evaluator 直接复用 `scripts/afl-showmap-gcc.sh`，因此只对 C/C++ 调用 `cc1`/`cc1plus` 形成覆盖数据。
- Fortran/Ada/D/asm/RTL/shell/COBOL ready groups 并非无效，而是需要对应前端或专用 harness：例如 `f951`、GNAT、D frontend、assembler scan、RTL dump/compile pass 或 shell-driven multi-file harness。
- 下一阶段应优先扩大 C/C++ 批量规模，随后为 assembly-scan、diagnostic、Fortran/asm/RTL 分别实现 evaluator，并保持报告中的语言分布口径。
