# InstanLLM 阶段覆盖率报告

生成时间：`2026-08-06T07:41:25Z`

测试范围：自有 LoongArch GCC fork 的编译器 CI 质量测试；不涉及网络安全测试。

## 本轮结论

| 指标 | 数值 |
| --- | --- |
| GroupLLM ready groups 总数 | 306 |
| 当前 evaluator 可直接处理的 C/C++ ready groups | 289 |
| 其他语言/专用 harness backlog | 17 |
| 本轮选择的 groups | 281 |
| InstanLLM ready | 269 |
| AFL++ covered | 269 |
| 本轮 C/C++ groups 选择率 | 97.23% |
| InstanLLM 生成 ready 率 | 95.73% |
| ready 程序 AFL covered 率 | 100.00% |
| C/C++ group 端到端 covered 率 | 95.73% |
| GroupLLM 全 ready 端到端 covered 比例 | 87.91% |

## 结果解读

- 当前已有 281/289 个 C/C++ ready groups 进入 InstanLLM 并完成评估；剩余 C/C++ ready groups 是新增 GroupLLM 输出或后续专用 harness 队列。
- 269/269 个 InstanLLM ready 程序均产生非空 AFL edge map，说明这些测例可以稳定驱动被测 GCC 前端执行，适合作为 CI corpus 候选。
- 未进入 covered 的 12 个 C/C++ group 停在 InstanLLM 生成阶段，其中 rejected 10 个、error 2 个；这不是 AFL/GCC 覆盖失败，应进入提示词、schema 或模型重试策略的修复队列。
- 本轮 union edge 为 263073，可作为后续 corpus admission 和趋势回归基线；单测例 `新增 edge` 为 0 的程序不一定无价值，但在入库优先级上应低于能增加 union edge 或具备强 oracle 的程序。
- gcov 源码覆盖率快照仍对应 260 个历史 covered corpus；当前 AFL covered 已为 269，源码覆盖率需按需重放后再更新。

## AFL edge map 统计

| 指标 | 数值 |
| --- | --- |
| covered programs | 269 |
| 本轮累计 union edge 数 | 263073 |
| 最小 edge map 条目 | 2631 |
| 最大 edge map 条目 | 101423 |
| 平均 edge map 条目 | 20320.1 |
| 中位 edge map 条目 | 3421.0 |

这些 edge map 条目来自 AFL++ instrumentation，不是 gcov 源码行覆盖率。`edge entries` 是单个测例触发的控制流边数量，`union edge` 是本轮所有 covered 测例触发的去重边集合。`union 占比` 表示某个测例单独覆盖了本轮 union edge 的多少；`新增 edge` 表示按表格顺序加入 corpus 时该测例带来的新增去重边数。

当前已有 gcov 源码覆盖快照，但它对应 260 个历史 covered corpus；当前 AFL covered 为 269。本轮优先评估 AFL feedback，不更新 gcov 汇报口径。

## 语言与 oracle 分布

| 语言 | GroupLLM ready | 本轮 InstanLLM |
| --- | --- | --- |
| ada | 1 | 0 |
| asm | 5 | 0 |
| c | 258 | 251 |
| c++ | 31 | 30 |
| cobol | 1 | 0 |
| d | 2 | 0 |
| fortran | 6 | 0 |
| shell | 2 | 0 |

| oracle kind | 数量 |
| --- | --- |
| assembly_scan | 38 |
| compile_failure | 14 |
| compile_success | 92 |
| compile_success_runtime_exit | 2 |
| differential | 9 |
| execute_differential | 1 |
| link | 1 |
| runtime_exit | 122 |
| unknown | 2 |

## 本轮程序明细

| candidate | language | status | edge entries | 新增 edge | union 占比 | source |
| --- | --- | --- | --- | --- | --- | --- |
| group-0001-0c4805f873ab | c | covered | 3390 | 3390 | 1.29% | group-0001-0c4805f873ab-c3e91e494c515b88.lasx_shuffle_xvldx_test.c |
| group-0002-391244b3a5a5 | c | covered | 3388 | 35 | 1.29% | group-0002-391244b3a5a5-af27f7825965c3d8.loongarch_feature_interplay_test.c |
| group-0003-0913e3e3f3bd | c | covered | 3360 | 6 | 1.28% | group-0003-0913e3e3f3bd-4fff5d4a663bd11f.loongarch_ice_combined.c |
| group-0004-827806713198 | c | covered | 48202 | 45171 | 18.32% | group-0004-827806713198-f21e5660029e06fe.sibcall_abi_padding_test.c |
| group-0005-07d7ec961d96 | c | covered | 3391 | 33 | 1.29% | group-0005-07d7ec961d96-3995527ff35fe72f.loongarch_bug_group.c |
| group-0008-9b3ffea126fb | c | covered | 10974 | 264 | 4.17% | group-0008-9b3ffea126fb-0ad3f985666fd778.loongarch_combined_bugs.c |
| group-0009-de11becdf0ee | c++ | covered | 3426 | 3384 | 1.30% | group-0009-de11becdf0ee-074f41c9f5982d53.loongarch_ice_test.cc |
| group-0010-92fb7029d82a | c | covered | 3374 | 3 | 1.28% | group-0010-92fb7029d82a-a0e30f47051025ac.loongarch_vector_round_shuffle_pick.c |
| group-0011-9268b3400021 | c | covered | 3390 | 5 | 1.29% | group-0011-9268b3400021-1394ad77e14c19af.loongarch_combined.c |
| group-0013-21f2fcd244d0 | c | covered | 17239 | 2707 | 6.55% | group-0013-21f2fcd244d0-98ad3cd2c1ddb66b.loongarch_vec_test.c |
| group-0014-eb55f2204699 | c | covered | 40256 | 5263 | 15.30% | group-0014-eb55f2204699-3c2ddd7100aa3157.test_128bit_shift_large_const.c |
| group-0015-eed89675e7a2 | c | covered | 3403 | 18 | 1.29% | group-0015-eed89675e7a2-4d35a92077ad8bdd.loongarch_vector_rounding.c |
| group-0016-fed9b0650eb5 | c | covered | 18517 | 2028 | 7.04% | group-0016-fed9b0650eb5-c3bd0d06cf8b5ccc.group_0016_test.c |
| group-0017-1534392225bf | c | covered | 50774 | 6835 | 19.30% | group-0017-1534392225bf-e8cc94742ea9280b.test_group_0017.c |
| group-0018-ee210b474afe | c | covered | 44041 | 3409 | 16.74% | group-0018-ee210b474afe-5097ec25f3575dbb.loongarch_ice_combine.c |
| group-0023-f6851481d876 | c | covered | 3365 | 0 | 1.28% | group-0023-f6851481d876-be45be22287f1596.test_lasx_simd.c |
| group-0024-1e4e0ae3bdf8 | c | covered | 3416 | 0 | 1.30% | group-0024-1e4e0ae3bdf8-64e63158c3626c01.lsx_combined_test.c |
| group-0026-677adba21106 | c | covered | 2631 | 7 | 1.00% | group-0026-677adba21106-83193461f1a53444.loongarch_ice_triggers.c |
| group-0028-2c0c7a7b367e | c | covered | 84305 | 28391 | 32.05% | group-0028-2c0c7a7b367e-d3f7013d37ee3e15.test_loongarch_opt.c |
| group-0030-30491d959663 | c | covered | 3379 | 0 | 1.28% | group-0030-30491d959663-2ae6a650bd537466.vector_shuffle_abi.c |
| group-0032-1c4e8fe9e883 | c | covered | 3392 | 0 | 1.29% | group-0032-1c4e8fe9e883-044e7baa6e85b24a.loongarch_inline_lsx_fp_test.c |
| group-0034-dae0859c28a0 | c | covered | 3390 | 1 | 1.29% | group-0034-dae0859c28a0-f835e6d4185ab5ba.loongarch_vec_ice_combined.c |
| group-0036-0e72d2cc9821 | c | covered | 3385 | 3 | 1.29% | group-0036-0e72d2cc9821-1292ad4cd62e2bb6.loongarch_multi_bug_test.c |
| group-0039-99e7421fda60 | c | covered | 3401 | 0 | 1.29% | group-0039-99e7421fda60-04134c548cb4ec97.lsx_vector_ice_test.c |
| group-0041-e097040f4fb4 | c | covered | 43647 | 1007 | 16.59% | group-0041-e097040f4fb4-77070609ab372113.loongarch_combined_test.c |
| group-0045-6d124569400f | c | covered | 3384 | 0 | 1.29% | group-0045-6d124569400f-9466fec431f64c52.loongarch_switch_vector_bitclear_pic.c |
| group-0046-22a0ab4e1324 | c | covered | 3379 | 0 | 1.28% | group-0046-22a0ab4e1324-6df02cfa3e920c05.loongarch_wrong_code_test.c |
| group-0047-2c73f0545c88 | c | covered | 19356 | 605 | 7.36% | group-0047-2c73f0545c88-286c3ec443691de3.group-0047-test.c |
| group-0048-615d38fae775 | c | covered | 3392 | 3 | 1.29% | group-0048-615d38fae775-c75a0e4cd144ee26.test_simd_interaction.c |
| group-0050-e3832b4ed26f | c | covered | 3369 | 0 | 1.28% | group-0050-e3832b4ed26f-e1fb707dd7bed921.test_bitreverse_constmul.c |
| group-0051-63fb78ca5761 | c | covered | 3370 | 0 | 1.28% | group-0051-63fb78ca5761-05f6c72667b73b59.test_loongarch_0051.c |
| group-0052-10da070c7760 | c | covered | 3383 | 2 | 1.29% | group-0052-10da070c7760-df129c57caa7fd38.loongarch_multi_feature_test.c |
| group-0054-3565fea53771 | c | covered | 3386 | 0 | 1.29% | group-0054-3565fea53771-0edddb60e3276db6.loongarch_complex_test.c |
| group-0055-244a4131ecb0 | c | covered | 3316 | 11 | 1.26% | group-0055-244a4131ecb0-951c0ed308a9167e.gcc-loongarch-mixed-bitreverse-bitint-asm.c |
| group-0056-625929b42350 | c | covered | 3389 | 24 | 1.29% | group-0056-625929b42350-0eaaf7868d366236.pr0056_mod_rot_cond_perm_vect.c |
| group-0057-94d18e5fc56d | c | covered | 3378 | 0 | 1.28% | group-0057-94d18e5fc56d-d64f5216218ee239.test_loongarch_lsx_0057.c |
| group-0058-72933998ab6c | c | covered | 3375 | 1 | 1.28% | group-0058-72933998ab6c-b1a2e9221c979944.test_combined.c |
| group-0059-594044a563a5 | c | covered | 3372 | 0 | 1.28% | group-0059-594044a563a5-fcbff63877d6a3f2.loongarch_combined_test.c |
| group-0060-5b21dee8e76b | c | covered | 82682 | 9984 | 31.43% | group-0060-5b21dee8e76b-8d4d3d1b1d04e4c6.group_0060_test.c |
| group-0061-d2b82b388a86 | c | covered | 3364 | 0 | 1.28% | group-0061-d2b82b388a86-2578779fb71aa078.loongarch_rotate_shuffle_shift.c |
| group-0063-8397bc2ee5f1 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0064-434a6d6881df | c | covered | 60027 | 2213 | 22.82% | group-0064-434a6d6881df-289773a41a476393.loongarch_loops.c |
| group-0066-abf70aca6470 | c | covered | 3369 | 0 | 1.28% | group-0066-abf70aca6470-0c7c9bfcdd4316d7.loongarch_vector_mix.c |
| group-0067-4cbbc78ee355 | c++ | covered | 11398 | 7804 | 4.33% | group-0067-4cbbc78ee355-83b2350ee60db569.tls_cost_array.cc |
| group-0068-a13a3a9f4afc | c | covered | 72233 | 4590 | 27.46% | group-0068-a13a3a9f4afc-dd63af4713fc089c.loongarch_combined_test.c |
| group-0071-3a82e414d135 | c | covered | 19690 | 449 | 7.48% | group-0071-3a82e414d135-1e95f0fa64d7fd22.loongarch_trigger_0071.c |
| group-0072-9ea960f72efe | c | covered | 3396 | 1 | 1.29% | group-0072-9ea960f72efe-453d41274871874c.loongarch_combined_test.c |
| group-0073-56d141a52ab8 | c | covered | 85771 | 3487 | 32.60% | group-0073-56d141a52ab8-62ad702def06c38b.loongarch_stress_test.c |
| group-0074-b8d618c3b085 | c | covered | 3406 | 1 | 1.29% | group-0074-b8d618c3b085-bb8abf09077c91eb.test_large_frame.c |
| group-0075-47e8e0a8ca85 | c | covered | 3392 | 18 | 1.29% | group-0075-47e8e0a8ca85-745d573a53a40bba.loongarch_opt_test.c |
| group-0076-0b68f1dfa9e4 | c | covered | 3382 | 2 | 1.29% | group-0076-0b68f1dfa9e4-8bc5ca9687fccdb4.lsx_combined_test.c |
| group-0077-a5bf52c0d1b7 | c | covered | 10928 | 594 | 4.15% | group-0077-a5bf52c0d1b7-d6fccaba9af477cf.loongarch_target_compile_test.c |
| group-0079-1f52b45231a0 | c | covered | 3396 | 4 | 1.29% | group-0079-1f52b45231a0-23a73b362d00d47e.loongarch_lto_simd_test.c |
| group-0081-45b512391f68 | c | covered | 3368 | 0 | 1.28% | group-0081-45b512391f68-4dc0a5fa57c306f3.group0081_test.c |
| group-0082-1b9531ee35ff | c++ | covered | 3452 | 46 | 1.31% | group-0082-1b9531ee35ff-d4fb105b02fabc96.test.cc |
| group-0083-d2eca85af029 | c | covered | 3388 | 4 | 1.29% | group-0083-d2eca85af029-29eb62b3958be34d.group_0083_combined.c |
| group-0084-b638845cad35 | c | covered | 50325 | 402 | 19.13% | group-0084-b638845cad35-e7bb92ba5254fc64.test_combined_la664.c |
| group-0085-dbfe7bd71499 | c | covered | 3384 | 0 | 1.29% | group-0085-dbfe7bd71499-3e735d3809f8b7c4.loongarch_integrated_test.c |
| group-0086-05e5645f0866 | c | covered | 3379 | 0 | 1.28% | group-0086-05e5645f0866-c4f8af981ff6da96.group_0086_test.c |
| group-0087-189b58aa0e34 | c | covered | 3369 | 0 | 1.28% | group-0087-189b58aa0e34-5071d8ac31c634a0.loongarch_rtl_interaction.c |
| group-0088-463272b62f42 | c | covered | 3369 | 0 | 1.28% | group-0088-463272b62f42-4b3e59c4f65fa3a6.group_0088_test.c |
| group-0089-eed807e28fb6 | c | covered | 3361 | 0 | 1.28% | group-0089-eed807e28fb6-c354800f267f308e.group_0089_test.c |
| group-0090-bcccba99226c | c | covered | 49806 | 296 | 18.93% | group-0090-bcccba99226c-9168b4de3f36a288.loongarch_asm_modifiers_ice.c |
| group-0091-fefcf0a2d3ae | c | covered | 3417 | 30 | 1.30% | group-0091-fefcf0a2d3ae-160d3dc40cc58571.lsx_reduction_test.c |
| group-0092-deca9e052b20 | c | covered | 3364 | 2 | 1.28% | group-0092-deca9e052b20-27ba6d9ccff2ba8a.test.c |
| group-0094-b2d9a9e96ee0 | c | covered | 44827 | 644 | 17.04% | group-0094-b2d9a9e96ee0-33c4a615f7c56b18.loongarch_merge_ccp.c |
| group-0096-6c50db238aad | c | covered | 3369 | 1 | 1.28% | group-0096-6c50db238aad-11652198fb7c815f.loongarch_features.c |
| group-0098-c6d740c8b77c | c++ | covered | 3446 | 20 | 1.31% | group-0098-c6d740c8b77c-5ba4649217370fc8.tls_simd_floor.cc |
| group-0099-01e15c94875c | c | covered | 18243 | 174 | 6.93% | group-0099-01e15c94875c-3a65532167173d93.loongarch64_test.c |
| group-0100-f979f03c9c7b | c | covered | 3424 | 30 | 1.30% | group-0100-f979f03c9c7b-1499d46765ee63b5.test_combined.c |
| group-0103-04955c9b5a35 | c | covered | 74192 | 883 | 28.20% | group-0103-04955c9b5a35-aaf7e59ab4058529.group_0103.c |
| group-0104-1c0fa7f9fc7c | c++ | covered | 3427 | 5 | 1.30% | group-0104-1c0fa7f9fc7c-2a060baece3d48e2.test_group_0104.cc |
| group-0106-04c71752fd06 | c | covered | 3315 | 0 | 1.26% | group-0106-04c71752fd06-6bfc5b1b2ff3e279.loongarch_combined_test.c |
| group-0107-0614e2eb43b8 | c | covered | 66088 | 1039 | 25.12% | group-0107-0614e2eb43b8-06d8cdb017af89bc.test_loongarch_carry_div_store.c |
| group-0108-03aea3be6f6e | c | covered | 3421 | 0 | 1.30% | group-0108-03aea3be6f6e-e943f0f0fed98d95.lasx_large_frame_lto_test.c |
| group-0109-69add1433b43 | c++ | covered | 3415 | 1 | 1.30% | group-0109-69add1433b43-801645a11f444a0d.group_0109_69add1433b43.cc |
| group-0111-6d07858ea670 | c | covered | 52932 | 566 | 20.12% | group-0111-6d07858ea670-eeaf7ba43300494b.group_0111_test.c |
| group-0116-97b6027caa66 | c | covered | 19262 | 202 | 7.32% | group-0116-97b6027caa66-6f8a07b54ecbb3f5.multi_target_regression.c |
| group-0117-d8dc60d81349 | c | covered | 69554 | 583 | 26.44% | group-0117-d8dc60d81349-cd77e71443dca01b.loongarch_pattern_test.c |
| group-0118-92ed2f61b145 | c++ | covered | 3380 | 32 | 1.28% | group-0118-92ed2f61b145-f48c6a0484a29949.test_random_loongarch.cc |
| group-0119-6c7de28738fc | c | covered | 10667 | 22 | 4.05% | group-0119-6c7de28738fc-ba71baebf65ef6bf.group_0119_test.c |
| group-0120-50fc51ef56f5 | c | covered | 72530 | 1939 | 27.57% | group-0120-50fc51ef56f5-3a6e8ed6b8ea7112.loongarch_bug_cluster.c |
| group-0121-c9620dfeb191 | c | covered | 82651 | 3976 | 31.42% | group-0121-c9620dfeb191-d3e7ca97237526da.combined_bitint_vector.c |
| group-0122-9d6e6d2eafdf | c | covered | 48668 | 330 | 18.50% | group-0122-9d6e6d2eafdf-ae26670342e5e734.test_group_0122.c |
| group-0123-d7d167885df0 | c | covered | 3380 | 3 | 1.28% | group-0123-d7d167885df0-032ecbf57bb0b4c9.group_0123_test.c |
| group-0124-34e18d2bf59f | c | covered | 78143 | 2263 | 29.70% | group-0124-34e18d2bf59f-c61024bedd536694.group_0124_34e18d2bf59f.c |
| group-0125-d953391414ce | c | covered | 3387 | 0 | 1.29% | group-0125-d953391414ce-55a39269ff6fac8f.loongarch_fp_vec_test.c |
| group-0128-7bb9a9990491 | c | covered | 3360 | 0 | 1.28% | group-0128-7bb9a9990491-ee6cebd29920bb64.loongarch_rtl_combine_vregs_test.c |
| group-0129-952f0a600edb | c | covered | 17190 | 91 | 6.53% | group-0129-952f0a600edb-ac508ec3d254a159.bug_trigger_set.c |
| group-0130-5894955ea17c | c++ | covered | 11463 | 103 | 4.36% | group-0130-5894955ea17c-4c268a43a2fb55e6.group-0130-5894955ea17c.cc |
| group-0131-c4690b132828 | c | covered | 3315 | 1 | 1.26% | group-0131-c4690b132828-11418b50587feb05.loongarch_combined_test.c |
| group-0133-42fbcee20dbf | c | covered | 17697 | 1034 | 6.73% | group-0133-42fbcee20dbf-d3fa50b002c82a19.lto_opt_oracle.c |
| group-0134-6afb42d58142 | c++ | covered | 3414 | 4 | 1.30% | group-0134-6afb42d58142-914d0887c5d4b5bc.tls_desc_musttail_zero_bitfield.cc |
| group-0135-6273305721d8 | c | covered | 10369 | 0 | 3.94% | group-0135-6273305721d8-1a1f08fedfacd2b1.combined_rtl_bugs.c |
| group-0136-692174877920 | c | covered | 61377 | 318 | 23.33% | group-0136-692174877920-bde21b2f8191683f.group-0136.c |
| group-0139-ce3fa5d94716 | c++ | covered | 3516 | 54 | 1.34% | group-0139-ce3fa5d94716-7ab15fa305129654.loongarch_lto_asan_lsx_lasx_test.cc |
| group-0141-60747dc2ecf8 | c | covered | 11191 | 5 | 4.25% | group-0141-60747dc2ecf8-1b8270d133f5aba3.loongarch_interaction_test.c |
| group-0142-4ff99e992f94 | c++ | covered | 3373 | 1 | 1.28% | group-0142-4ff99e992f94-4f59cc16331dd218.loongarch_mixed_test.cc |
| group-0145-6f6694d89941 | c | covered | 3376 | 0 | 1.28% | group-0145-6f6694d89941-9afa2ab58343267a.loongarch_rtl_interaction_test.c |
| group-0146-ff272143ba6e | c | covered | 17390 | 41 | 6.61% | group-0146-ff272143ba6e-96135235b1bba28c.loongarch_combined_0146.c |
| group-0147-21a964bebded | c | covered | 48522 | 382 | 18.44% | group-0147-21a964bebded-759047a1134a273a.group_0147_test.c |
| group-0151-d833c79310de | c | covered | 15447 | 57 | 5.87% | group-0151-d833c79310de-7784876f0ccbdca7.vector_shift_combine_ternary.c |
| group-0157-43f51e674b00 | c | covered | 21524 | 568 | 8.18% | group-0157-43f51e674b00-a660e1b321ddd012.loongarch_ice_combo_0157.c |
| group-0158-5cd3746b6a35 | c++ | covered | 3416 | 1 | 1.30% | group-0158-5cd3746b6a35-e204e3846c678032.vector_musttail_zwb.cc |
| group-0159-dff9210641a4 | c | covered | 3412 | 2 | 1.30% | group-0159-dff9210641a4-abd54d5002ace5fb.loongarch_asm_fcsr_pragma_imm.c |
| group-0162-50daf4e1625d | c | covered | 3384 | 1 | 1.29% | group-0162-50daf4e1625d-15a4cad77a6827d5.loongarch_simd_bitint_stack.c |
| group-0165-e71fdecf648d | c | covered | 3382 | 0 | 1.29% | group-0165-e71fdecf648d-7a113bbc3c35952b.test.c |
| group-0170-25730b2b76d8 | c | covered | 3379 | 2 | 1.28% | group-0170-25730b2b76d8-124c60d5aeefab84.test_bitint_extdce.c |
| group-0173-ebc70fe3418c | c | covered | 10444 | 0 | 3.97% | group-0173-ebc70fe3418c-f1417032ce0d15aa.loongarch_fp_signal_unwind.c |
| group-0174-8ad80e188e43 | c | covered | 67476 | 876 | 25.65% | group-0174-8ad80e188e43-4c9989c5532b3b85.test.c |
| group-0175-495d8ce50a41 | c | covered | 3360 | 0 | 1.28% | group-0175-495d8ce50a41-66876025baea9eb1.group_0175_test.c |
| group-0178-5f70e4758aa3 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0179-f4cd426cd4df | c | covered | 3339 | 0 | 1.27% | group-0179-f4cd426cd4df-2269c4bb606bcfad.combined_decimal_fixed_sign.c |
| group-0181-2adbdf2086ca | c | covered | 3307 | 0 | 1.26% | group-0181-2adbdf2086ca-a6127574fd9cc921.test.c |
| group-0184-732fc4aee0bb | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0186-d95327e53907 | c | covered | 40453 | 34 | 15.38% | group-0186-d95327e53907-69a968e2c14aa755.loongarch_const_mul_asm_avg.c |
| group-0188-67da4e37b430 | c | covered | 3409 | 0 | 1.30% | group-0188-67da4e37b430-4a0f9f6fe51380ad.loongarch_combined_bugs.c |
| group-0189-b14296f2ae8b | c | covered | 3374 | 0 | 1.28% | group-0189-b14296f2ae8b-d54302f1119e9cc7.loongarch_group_0189.c |
| group-0190-5f7761799dd3 | c | covered | 3377 | 1 | 1.28% | group-0190-5f7761799dd3-99b981d4d914150e.lasx_shuffle_extdce.c |
| group-0192-1feb8cce1a93 | c | covered | 59058 | 247 | 22.45% | group-0192-1feb8cce1a93-549f9110dd957b6b.group_0192_1feb8cce1a93.c |
| group-0196-3a0deb9fe66f | c | covered | 3360 | 0 | 1.28% | group-0196-3a0deb9fe66f-a46c9fc154d85bed.loongarch_rtl_interaction.c |
| group-0199-47a45403c382 | c | covered | 79993 | 2582 | 30.41% | group-0199-47a45403c382-1d0058451fcb501e.test_group_0199.c |
| group-0200-d8a0ce8d27c6 | c | covered | 22184 | 799 | 8.43% | group-0200-d8a0ce8d27c6-e41aa19e8c30e0f1.test_loongarch_vec_ivopts.c |
| group-0204-f0aa7586a826 | c++ | covered | 3426 | 0 | 1.30% | group-0204-f0aa7586a826-d490714c9aba4daf.group-0204-test.cc |
| group-0205-a4624d96594d | c | covered | 81394 | 2139 | 30.94% | group-0205-a4624d96594d-68f8da784d986bfe.loongarch_group_0205.c |
| group-0206-547db4b6a6fc | c++ | covered | 16628 | 5039 | 6.32% | group-0206-547db4b6a6fc-4270cbaa7f7f3db3.loongarch_combined_test.cc |
| group-0207-dd90715844fe | c | covered | 10392 | 3 | 3.95% | group-0207-dd90715844fe-2ee2f40086422448.test_partial_vec_extdce.c |
| group-0208-297cb3a0a365 | c | covered | 10414 | 0 | 3.96% | group-0208-297cb3a0a365-9afe0cb22c72fb79.test_loop_recip_vector.c |
| group-0209-0f927417a935 | c | covered | 3481 | 0 | 1.32% | group-0209-0f927417a935-c3fc2d082791b3eb.gcc_bug_group_0209_test.c |
| group-0211-548514205cfd | c | covered | 52443 | 58 | 19.93% | group-0211-548514205cfd-bb15b6df76593710.bitint_fp_shortcircuit.c |
| group-0212-1f438e41ad96 | c | covered | 72341 | 1390 | 27.50% | group-0212-1f438e41ad96-9c4d05f3a04af844.group_0212_test.c |
| group-0213-b5dc2f787258 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0214-a38e6de734fd | c | covered | 41600 | 117 | 15.81% | group-0214-a38e6de734fd-864f01d8007588e2.test.c |
| group-0215-dfbfe60b2a5a | c | covered | 3384 | 1 | 1.29% | group-0215-dfbfe60b2a5a-4243bf23af382342.lsx_ext_dce_combined.c |
| group-0219-150aadd38b6f | c | covered | 63960 | 776 | 24.31% | group-0219-150aadd38b6f-196a316ad39e79dc.group_0219_test.c |
| group-0220-dd6ed1456545 | c | covered | 3372 | 0 | 1.28% | group-0220-dd6ed1456545-4393807064138574.test_group_0220.c |
| group-0221-7abb62f21ecc | c | covered | 10843 | 71 | 4.12% | group-0221-7abb62f21ecc-8b36f5b46ba80349.loongarch_missed_opt_combined.c |
| group-0222-c0f5cd85bc8a | c | covered | 78390 | 1180 | 29.80% | group-0222-c0f5cd85bc8a-52d8ffb96b9fc3de.group_0222_c0f5cd85bc8a.c |
| group-0223-be3a6f0116f1 | c | covered | 3380 | 2 | 1.28% | group-0223-be3a6f0116f1-7ce5702bec17fe31.bug_combination_test.c |
| group-0227-04ceca108b8c | c | covered | 34499 | 6 | 13.11% | group-0227-04ceca108b8c-90d518165138b074.loongarch_macro_hardreg.c |
| group-0231-a293fcedf85c | c | covered | 10865 | 0 | 4.13% | group-0231-a293fcedf85c-3ebee6bc4344f301.bitint_cond_assign_mixed_arith.c |
| group-0232-dc8b4157117e | c++ | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0235-312796560b87 | c | covered | 3369 | 0 | 1.28% | group-0235-312796560b87-4922fcfeba57e9b1.loongarch_combined_test.c |
| group-0236-9905f524060f | c | covered | 3376 | 0 | 1.28% | group-0236-9905f524060f-2b03a593f0aa3efa.lsx_lasx_bitcopy_asm_goto.c |
| group-0239-2131a5b042ad | c | covered | 3393 | 0 | 1.29% | group-0239-2131a5b042ad-ba68115e3c4febe8.lsx_fixedpoint_test.c |
| group-0240-fb9488c18a6d | c | covered | 3329 | 5 | 1.27% | group-0240-fb9488c18a6d-125089408a562175.pr_group_0240.c |
| group-0245-7da9cc729c4a | c | covered | 3379 | 2 | 1.28% | group-0245-7da9cc729c4a-32b3d4af92936536.lsx_reorder_classify_bitrev.c |
| group-0249-62041777e7ac | c | covered | 3391 | 0 | 1.29% | group-0249-62041777e7ac-49a51ddda0486716.group_0249_test.c |
| group-0251-91d7de9a6514 | c | covered | 47760 | 694 | 18.15% | group-0251-91d7de9a6514-f1a8a4b2eca5e82f.shift_combine_test.c |
| group-0252-71bdeb7cb6ec | c | covered | 3378 | 0 | 1.28% | group-0252-71bdeb7cb6ec-1a561edbc93b64b4.test_vec_perm_alias.c |
| group-0256-fb8940359632 | c | covered | 67730 | 200 | 25.75% | group-0256-fb8940359632-dc59ebc325af2731.test.c |
| group-0257-fe0123fc88ed | c | covered | 3360 | 0 | 1.28% | group-0257-fe0123fc88ed-b46dcc721ff35fd5.lsx_combined_test.c |
| group-0260-da4e79c9ada9 | c | covered | 3343 | 33 | 1.27% | group-0260-da4e79c9ada9-4685b8724f0359ad.test_group_0260.c |
| group-0261-d0409f52ed2a | c | covered | 75366 | 1102 | 28.65% | group-0261-d0409f52ed2a-9d213dd5bb05026a.pr117608-116488-125291.c |
| group-0263-f26811ea1dfb | c | covered | 3368 | 0 | 1.28% | group-0263-f26811ea1dfb-185309ef8a0b5bd6.loongarch_combined_test.c |
| group-0264-1c5c46c8c616 | c++ | covered | 54856 | 35811 | 20.85% | group-0264-1c5c46c8c616-1ee5a37b28fceba5.loongarch_build_failure_test.cc |
| group-0266-f52db01b314f | c | covered | 62950 | 1121 | 23.93% | group-0266-f52db01b314f-fbf674e6b22e4250.loongarch_bitint_ice.c |
| group-0267-2312606076da | c | covered | 3320 | 0 | 1.26% | group-0267-2312606076da-cb6c5ee4512703af.sad_sibcall_signext.c |
| group-0269-fff855c40381 | c | covered | 63589 | 545 | 24.17% | group-0269-fff855c40381-44160f264abc81af.test_bug_0269.c |
| group-0270-7d91f299ef5a | c | covered | 3397 | 0 | 1.29% | group-0270-7d91f299ef5a-b6fbcf135eba3b12.loongarch_group_0270.c |
| group-0272-265010186dc0 | c | covered | 3360 | 0 | 1.28% | group-0272-265010186dc0-dde4e8808f44f9ff.loongarch_vector_combine_test.c |
| group-0274-89c70bffc35f | c | covered | 3376 | 0 | 1.28% | group-0274-89c70bffc35f-dc12de57d32c09e8.lsx_floor_cmp_test.c |
| group-0277-ef5bb1bb4d7a | c | covered | 3365 | 5 | 1.28% | group-0277-ef5bb1bb4d7a-3ff44166020d0856.test.c |
| group-0278-74e5b118ce56 | c | covered | 44986 | 284 | 17.10% | group-0278-74e5b118ce56-fb1711c98ffa7502.pr121413_96692_123635.c |
| group-0279-db5d6117651e | c | covered | 3396 | 0 | 1.29% | group-0279-db5d6117651e-29ea6f3521627577.loongarch_combined_test.c |
| group-0280-0cd5e9744e98 | c | covered | 3394 | 0 | 1.29% | group-0280-0cd5e9744e98-9497e0b56c7bfdf3.combined_loongarch_bugs.c |
| group-0283-d6b19851075b | c | covered | 12010 | 10 | 4.57% | group-0283-d6b19851075b-c314e8c11e7d8def.loongarch_pragma_scope_test.c |
| group-0284-cb6b51df3e7f | c | covered | 43993 | 80 | 16.72% | group-0284-cb6b51df3e7f-f46033011bba2667.pr117599.c |
| group-0285-954b72c7d525 | c++ | covered | 11450 | 7 | 4.35% | group-0285-954b72c7d525-9eff8f4cf4c16e32.group_0285_954b72c7d525_test.cc |
| group-0286-1c6fb29175d1 | c | covered | 10439 | 0 | 3.97% | group-0286-1c6fb29175d1-9fa18fde720b3d9a.gcc_loongarch_ice_test.c |
| group-0287-c21e85f9a4ac | c++ | covered | 11446 | 1 | 4.35% | group-0287-c21e85f9a4ac-e1fa3b20ca9cd2e1.group_0287_test.cc |
| group-0288-53a51b5b937d | c | covered | 3469 | 4 | 1.32% | group-0288-53a51b5b937d-358a3da40d5b6418.lsx_lasx_combined_test.c |
| group-0289-2e7508d2e7b6 | c | covered | 58042 | 208 | 22.06% | group-0289-2e7508d2e7b6-74ec12f8dc802c0e.loongarch_asm_frame_sext.c |
| group-0290-7352abfc6eb1 | c | covered | 19770 | 94 | 7.52% | group-0290-7352abfc6eb1-e2f7f4681d7d8301.test.c |
| group-0292-074bab91eedd | c++ | covered | 3478 | 3 | 1.32% | group-0292-074bab91eedd-cbffc50b568e9502.group-0292-074bab91eedd.cc |
| group-0293-e51311280030 | c | covered | 3399 | 0 | 1.29% | group-0293-e51311280030-f0d48c2e7a836e56.loongarch_bitfield_modulo_memcpy_test.c |
| group-0294-774ca5468a39 | c++ | covered | 41505 | 12058 | 15.78% | group-0294-774ca5468a39-32f7e09c4123f197.lto_dotprod_subreg.cc |
| group-0295-a5757b57e7f2 | c++ | covered | 3450 | 3 | 1.31% | group-0295-a5757b57e7f2-c02ebafb1befc534.group-0295-a5757b57e7f2.cc |
| group-0297-f26c4ca56e53 | c | covered | 19471 | 79 | 7.40% | group-0297-f26c4ca56e53-f913213c64f88267.loongarch_vec_test.c |
| group-0298-2dc40b27ee4f | c++ | covered | 3427 | 0 | 1.30% | group-0298-2dc40b27ee4f-a2d2263a049f3c86.loongarch_combined_test.cc |
| group-0299-7b2d5fd4d455 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0300-64b9939e6c1c | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0301-0bb7d03e72ca | c | covered | 74725 | 735 | 28.40% | group-0301-0bb7d03e72ca-457898afc326b14a.loongarch_combined_test.c |
| group-0303-265753bb5db5 | c | covered | 3388 | 0 | 1.29% | group-0303-265753bb5db5-4c7d0a05ebb79d16.combined_test.c |
| group-0305-adb8610e4820 | c | covered | 3399 | 0 | 1.29% | group-0305-adb8610e4820-35470ab457f1018d.test_loongarch_group.c |
| group-0309-6b1f156e02cd | c | covered | 70889 | 1697 | 26.95% | group-0309-6b1f156e02cd-d4ff7584b8ef06df.loongarch_combined_test.c |
| group-0311-1da742e5d24d | c | covered | 17351 | 143 | 6.60% | group-0311-1da742e5d24d-4d8b5243ab2e3123.carry_ext_dce_test.c |
| group-0312-a68c4451b12b | c | covered | 63250 | 85 | 24.04% | group-0312-a68c4451b12b-afc7fba4398a8d7e.loongarch_combined_test.c |
| group-0313-b5e1e13a5cf8 | c | covered | 3393 | 0 | 1.29% | group-0313-b5e1e13a5cf8-81c9d86958ef7df6.loongarch_vector_glue_test.c |
| group-0315-bd197ce7d2f8 | c | covered | 3364 | 0 | 1.28% | group-0315-bd197ce7d2f8-676ce82addc091ce.group_0315_simd_test.c |
| group-0320-07742f0dfbe5 | c | covered | 19328 | 29 | 7.35% | group-0320-07742f0dfbe5-c33ee3f8fbbfe1ae.loongarch_lasx_vector_ice.c |
| group-0321-10370a6981a2 | c | covered | 3373 | 0 | 1.28% | group-0321-10370a6981a2-af6755d6d8cb4062.loongarch_multi_bug.c |
| group-0322-4dffbeed31d4 | c | covered | 3376 | 0 | 1.28% | group-0322-4dffbeed31d4-34fc25c8e0fc1fd9.loongarch_multi_feature_test.c |
| group-0323-8b93bb1fd357 | c | covered | 49473 | 196 | 18.81% | group-0323-8b93bb1fd357-d817f91f2c64537f.loongarch_combined_asm_modulo.c |
| group-0324-6301f9f3df33 | c | covered | 3362 | 0 | 1.28% | group-0324-6301f9f3df33-8c2a6d318b2d6cbb.loongarch_codegen_interaction.c |
| group-0325-b4ee70f0a808 | c | covered | 3365 | 0 | 1.28% | group-0325-b4ee70f0a808-159b1271b8f12897.combined_opt_test.c |
| group-0326-d9ce14204dd0 | c | covered | 38282 | 8 | 14.55% | group-0326-d9ce14204dd0-1551c0f51c5de527.loongarch_asm_glue_test.c |
| group-0327-5393075f3dfe | c | covered | 62631 | 415 | 23.81% | group-0327-5393075f3dfe-7d6b34c976fdfd49.grp0327.c |
| group-0328-575f8e51c2e4 | c | covered | 3374 | 0 | 1.28% | group-0328-575f8e51c2e4-862571f8f359ecf3.test.c |
| group-0329-b88b58aba8c0 | c | covered | 3388 | 0 | 1.29% | group-0329-b88b58aba8c0-1a61512654056b35.loongarch_fpu_lasx_test.c |
| group-0330-0762bb115401 | c | covered | 45523 | 90 | 17.30% | group-0330-0762bb115401-a8e670d7f605e93a.loongarch_la664_test.c |
| group-0331-2d7e193004ab | c | covered | 3376 | 0 | 1.28% | group-0331-2d7e193004ab-64265a4572724fcd.loongarch_simd_lto_bitrev.c |
| group-0332-9f17f783bf71 | c | covered | 3375 | 0 | 1.28% | group-0332-9f17f783bf71-c748cc6ed7f74e57.loongarch_mixed_bugs.c |
| group-0333-2ad15e41d08e | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0334-6316748f38a2 | c | covered | 82889 | 1620 | 31.51% | group-0334-6316748f38a2-2223cf285aa3736d.test_0334.c |
| group-0335-70434d9ba268 | c | covered | 77470 | 592 | 29.45% | group-0335-70434d9ba268-3bac1b097d84aedd.group-0335-70434d9ba268.c |
| group-0336-85bf4fa5d890 | c | covered | 3309 | 0 | 1.26% | group-0336-85bf4fa5d890-cd3f863ad62f27f3.lasx_shift_vcond_test.c |
| group-0337-76d75a69c8d8 | c | covered | 10864 | 3 | 4.13% | group-0337-76d75a69c8d8-9da150aa30322f40.loongarch_mixed_opt_test.c |
| group-0341-106b17b09ec0 | c | covered | 3401 | 0 | 1.29% | group-0341-106b17b09ec0-32d6c4a41115e784.group_0341_test.c |
| group-0342-a96a08af0996 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0343-b93e559f4b89 | c | covered | 15739 | 25 | 5.98% | group-0343-b93e559f4b89-d6e9e2aca41df815.test_mux_rotate_ice.c |
| group-0344-c48b5f661c0b | c | covered | 58895 | 153 | 22.39% | group-0344-c48b5f661c0b-575b733d5ac05a3d.loongarch_combined_test.c |
| group-0345-83c2b63f9dd2 | c | covered | 66283 | 325 | 25.20% | group-0345-83c2b63f9dd2-8260154f9ceabbc7.loongarch_reload_vector.c |
| group-0346-64dc84984dcf | c | covered | 3380 | 0 | 1.28% | group-0346-64dc84984dcf-70460cc5fe891c93.vectorizer_combined_test.c |
| group-0347-7218f3c65014 | c++ | covered | 3375 | 0 | 1.28% | group-0347-7218f3c65014-0090ad1d3ba655b6.carry_chain_test.cc |
| group-0349-58d0cd9c256e | c | covered | 3369 | 0 | 1.28% | group-0349-58d0cd9c256e-5278ca3d9f215406.lsx_vector_ice_test.c |
| group-0350-921425bd301e | c | covered | 3376 | 0 | 1.28% | group-0350-921425bd301e-01048a76fa013b56.test_combined_lsx.c |
| group-0351-4e45024a247b | c++ | covered | 3425 | 9 | 1.30% | group-0351-4e45024a247b-d15f33ea6d00bcb7.loongarch_multi_bug_test.cc |
| group-0352-522be0e8844c | c | covered | 3361 | 0 | 1.28% | group-0352-522be0e8844c-ba6f36b47d84b117.loongarch_simd_test.c |
| group-0353-ea09d7b73ed4 | c | covered | 3319 | 1 | 1.26% | group-0353-ea09d7b73ed4-afd4b310b2443624.group_0353_test.c |
| group-0354-e948498ea0b7 | c | covered | 48617 | 232 | 18.48% | group-0354-e948498ea0b7-03cd25d7133a0d81.loongarch_integration_test.c |
| group-0355-ce71044bb13f | c | covered | 3367 | 0 | 1.28% | group-0355-ce71044bb13f-4a1d6cae8bcc8cd7.loongarch_vector_ops.c |
| group-0356-f45a13d03531 | c | covered | 3360 | 0 | 1.28% | group-0356-f45a13d03531-d1b83bda0a547751.lsx_vector_bugs.c |
| group-0359-e887d2ba2547 | c++ | covered | 39919 | 1500 | 15.17% | group-0359-e887d2ba2547-db00027863a1f887.loongarch_build_errors.cc |
| group-0360-61b7f0a7add8 | c++ | covered | 24635 | 2051 | 9.36% | group-0360-61b7f0a7add8-0777a92d308e749c.loongarch_mixed_regression.cc |
| group-0365-681786eb5e5d | c | covered | 3499 | 13 | 1.33% | group-0365-681786eb5e5d-9b76e01e9e504bcf.loongarch_combined_test.c |
| group-0367-43ad87ca8227 | c | covered | 3360 | 0 | 1.28% | group-0367-43ad87ca8227-e0cdbcca4d5728bb.loongarch_vector_ifcombine_zeroext.c |
| group-0368-6f9ebd07320f | c | covered | 3453 | 0 | 1.31% | group-0368-6f9ebd07320f-32b4cfe20f2d8580.lsx_vector_compare_diag.c |
| group-0373-5375c17201cd | c | covered | 3377 | 0 | 1.28% | group-0373-5375c17201cd-f4671118e0f1f41c.loongarch_rtl_pass_interactions.c |
| group-0376-50d13aa1e3dd | c | covered | 3423 | 0 | 1.30% | group-0376-50d13aa1e3dd-9a81f7861a55a1e2.loongarch_multi_feature_test.c |
| group-0377-545ce9aa6e5a | c | covered | 3376 | 0 | 1.28% | group-0377-545ce9aa6e5a-f7cd8421e0dd37be.lasx_vec_compare_shuffle_dot.c |
| group-0381-b9ce42977a84 | c | covered | 3379 | 0 | 1.28% | group-0381-b9ce42977a84-411947ed271d5921.loongarch_multi_feature_test.c |
| group-0382-688acf06a661 | c | covered | 3376 | 0 | 1.28% | group-0382-688acf06a661-f359ff749a62f438.lsx_lasx_combined_test.c |
| group-0383-a38026889c6f | c | covered | 76285 | 2547 | 29.00% | group-0383-a38026889c6f-5dd64ba8f29cfdfa.loongarch_ice_trigger.c |
| group-0389-151dc48541ae | c | covered | 3369 | 0 | 1.28% | group-0389-151dc48541ae-d142c7c38200f60a.lsx_lasx_combined_test.c |
| group-0390-5caa9ba78cbc | c | covered | 18986 | 93 | 7.22% | group-0390-5caa9ba78cbc-2ca352e1db62e551.loongarch_ice_test.c |
| group-0392-9de8c84c57bb | c | covered | 3407 | 0 | 1.30% | group-0392-9de8c84c57bb-b6f7a79be5ef1ecc.loongarch_combined_test.c |
| group-0393-0d7cebab5f38 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0397-7e9c9c66d0eb | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0400-9944af5e1b95 | c | covered | 3416 | 0 | 1.30% | group-0400-9944af5e1b95-c3e1cc6f370a2d60.loongarch_combined_bugs.c |
| group-0405-dcc691c594e5 | c | covered | 11090 | 2 | 4.22% | group-0405-dcc691c594e5-8b3cf449870c3819.test_combined.c |
| group-0406-3cc212ed34b9 | c | covered | 3360 | 0 | 1.28% | group-0406-3cc212ed34b9-3a8c8ad2358f3167.pr0406_vect_eh_abi.c |
| group-0412-7bca4aa1f0b0 | c | covered | 3386 | 0 | 1.29% | group-0412-7bca4aa1f0b0-cd34968082a6108f.test_group_0412.c |
| group-0414-cfaf284c2521 | c | covered | 3373 | 0 | 1.28% | group-0414-cfaf284c2521-9cf0ed25a2e700b8.group-0414.c |
| group-0420-e8598185ca48 | c | covered | 3388 | 0 | 1.29% | group-0420-e8598185ca48-382c499cecbf9834.loongarch_integrated.c |
| group-0424-a332f22691dc | c | covered | 3461 | 0 | 1.32% | group-0424-a332f22691dc-bc709db920cccc0d.lsx_cost_profile_test.c |
| group-0426-6cd7462ce0aa | c++ | covered | 3410 | 0 | 1.30% | group-0426-6cd7462ce0aa-b7385e146a9b97ca.loongarch_regression.cc |
| group-0427-fc13f81483d4 | c | covered | 3435 | 0 | 1.31% | group-0427-fc13f81483d4-0ead11fd24bc3e97.loongarch_multi_feature_checksum.c |
| group-0428-a1faabd05927 | c | covered | 3302 | 0 | 1.26% | group-0428-a1faabd05927-c2a996c03497360e.reg_vect_widen_test.c |
| group-0432-92a0845cabf8 | c | covered | 32023 | 2367 | 12.17% | group-0432-92a0845cabf8-3a6031d411b33844.loongarch_combined_bugs.c |
| group-0433-48b227c9ebe1 | c++ | covered | 87606 | 24053 | 33.30% | group-0433-48b227c9ebe1-277ccfbc6e3e1874.loongarch_wrongcode_test.cc |
| group-0436-9cacc3b17f37 | c | covered | 16161 | 29 | 6.14% | group-0436-9cacc3b17f37-17198c60eb78e6a3.loongarch_bug0436.c |
| group-0437-3d116cea05e6 | c++ | covered | 3420 | 0 | 1.30% | group-0437-3d116cea05e6-feaac0e9f70a46a6.group-0437-3d116cea05e6.cc |
| group-0440-40d4040e1f0b | c | covered | 10450 | 0 | 3.97% | group-0440-40d4040e1f0b-e28e1e238c6a1bbb.test_loongarch.c |
| group-0449-1b705eaf7746 | c | covered | 3395 | 1 | 1.29% | group-0449-1b705eaf7746-e4951e4961328ac8.combined_test.c |
| group-0456-e6c616916e0f | c | covered | 52977 | 383 | 20.14% | group-0456-e6c616916e0f-9cf530524932f054.loongarch_ext_dce_and_reloc.c |
| group-0457-c3b336cf0b30 | c | covered | 82289 | 1219 | 31.28% | group-0457-c3b336cf0b30-9208935fba27d866.loongarch_slp_ice_test.c |
| group-0458-fac4fa4205b7 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0460-933bff55a955 | c | covered | 62730 | 181 | 23.85% | group-0460-933bff55a955-1d541518e2e54102.group-0460-933bff55a955.c |
| group-0465-69a4d4bb4610 | c | covered | 3381 | 3 | 1.29% | group-0465-69a4d4bb4610-10bcee65f68ffedd.test_group_0465.c |
| group-0468-7629192b72aa | c | covered | 3365 | 0 | 1.28% | group-0468-7629192b72aa-b43431bafb65066a.bitint_mux_nan_test.c |
| group-0472-333323c70198 | c | covered | 66760 | 793 | 25.38% | group-0472-333323c70198-7bf0a45de669a965.bitint_expand_bool_warning.c |
| group-0476-06e622e087b7 | c | covered | 3368 | 0 | 1.28% | group-0476-06e622e087b7-b49a16bda5b9b5f3.group-0476.c |
| group-0478-d735eded410c | c | covered | 55776 | 62 | 21.20% | group-0478-d735eded410c-4d34f30a7cc93a7a.loongarch_group_test.c |
| group-0479-f9a1a4d88a32 | c | covered | 3443 | 0 | 1.31% | group-0479-f9a1a4d88a32-b4e1e50dd283af96.bug_combination.c |
| group-0480-4b4dede1bdbb | c | covered | 17684 | 79 | 6.72% | group-0480-4b4dede1bdbb-2dbf08e078d1fee4.test.c |
| group-0487-b76d3d891b12 | c | covered | 10858 | 0 | 4.13% | group-0487-b76d3d891b12-4d1241a48a437c8f.test_combined.c |
| group-0488-b608dba11bb3 | c | covered | 101423 | 4421 | 38.55% | group-0488-b608dba11bb3-9bf5e33a219763f7.loongarch_slp_builtin_shuffle_cost.c |
| group-0489-88e918e55a6a | c | covered | 38353 | 39 | 14.58% | group-0489-88e918e55a6a-efa86d8cb63cb542.loongarch_ice_trio.c |
| group-0490-5449339f832d | c | covered | 3393 | 0 | 1.29% | group-0490-5449339f832d-059d4cfc2dae461b.loongarch_combined_test.c |
| group-0491-abcf1d3e5379 | c | covered | 3403 | 0 | 1.29% | group-0491-abcf1d3e5379-9cfd9f34b0a49be3.combined_loongarch_tests.c |
| group-0492-b0998f6fc522 | c | covered | 68836 | 142 | 26.17% | group-0492-b0998f6fc522-f2543a2d76cec6aa.group_0492_b0998f6fc522.c |
| group-0529-a11a75c46ae8 | c | covered | 3390 | 0 | 1.29% | group-0529-a11a75c46ae8-be034624fa4dda9e.test_loongarch_vec_bitfield.c |
| group-0530-5a84eabc2cb8 | c | covered | 3368 | 0 | 1.28% | group-0530-5a84eabc2cb8-fc841087e8f8982b.loongarch_rtl_regression.c |
| group-0531-156cec5c0d07 | c | covered | 18008 | 19 | 6.85% | group-0531-156cec5c0d07-08c5b10e4d4bebf1.loongarch_interplay.c |
| group-0533-ddf43aaba425 | c | covered | 82985 | 174 | 31.54% | group-0533-ddf43aaba425-68fe2c7eb01ecbb7.test.c |
| group-0534-0faaf3313288 | c++ | covered | 24912 | 948 | 9.47% | group-0534-0faaf3313288-72ff39206adad314.group_0534_test.cc |
| group-0536-f05bee7b796f | c | covered | 3509 | 6 | 1.33% | group-0536-f05bee7b796f-f2237ea50553e6ba.lsx_diag_test.c |
| group-0537-fe61918e3310 | c | covered | 3376 | 0 | 1.28% | group-0537-fe61918e3310-254b8fd56654a0a9.test-0537.c |
| group-0538-e9a09166f242 | c | covered | 40099 | 6 | 15.24% | group-0538-e9a09166f242-5462910003dcb458.loongarch_asm_inline_test.c |
| group-0539-98f8ceaa9d33 | c | covered | 3366 | 3 | 1.28% | group-0539-98f8ceaa9d33-adbecca33e15e265.group-0539.c |

## 当前边界与后续工作

- 当前 evaluator 直接复用 `scripts/afl-showmap-gcc.sh`，因此只对 C/C++ 调用 `cc1`/`cc1plus` 形成覆盖数据。
- Fortran/Ada/D/asm/RTL/shell/COBOL ready groups 并非无效，而是需要对应前端或专用 harness：例如 `f951`、GNAT、D frontend、assembler scan、RTL dump/compile pass 或 shell-driven multi-file harness。
- C/C++ ready groups 已完成全量 InstanLLM + AFL edge 评估，并已接入 gcov 源码行/函数覆盖重放。下一阶段应细化 oracle，并为 assembly-scan、diagnostic、Fortran/asm/RTL 分别实现 evaluator。
