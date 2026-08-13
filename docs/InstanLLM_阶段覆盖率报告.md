# InstanLLM 阶段覆盖率报告

生成时间：`2026-08-13T06:56:48Z`

测试范围：自有 LoongArch GCC fork 的编译器 CI 质量测试；不涉及网络安全测试。

## 本轮结论

| 指标 | 数值 |
| --- | --- |
| GroupLLM ready groups 总数 | 535 |
| 当前 evaluator 可直接处理的 C/C++ ready groups | 510 |
| 其他语言/专用 harness backlog | 25 |
| 本轮选择的 groups | 496 |
| InstanLLM ready | 471 |
| AFL++ covered | 471 |
| 本轮 C/C++ groups 选择率 | 97.25% |
| InstanLLM 生成 ready 率 | 94.96% |
| ready 程序 AFL covered 率 | 100.00% |
| C/C++ group 端到端 covered 率 | 94.96% |
| GroupLLM 全 ready 端到端 covered 比例 | 88.04% |

## 结果解读

- 当前已有 496/510 个 C/C++ ready groups 进入 InstanLLM 并完成评估；剩余 C/C++ ready groups 是新增 GroupLLM 输出或后续专用 harness 队列。
- 471/471 个 InstanLLM ready 程序均产生非空 AFL edge map，说明这些测例可以稳定驱动被测 GCC 前端执行，适合作为 CI corpus 候选。
- 未进入 covered 的 25 个 C/C++ group 停在 InstanLLM 生成阶段，其中 rejected 21 个、error 4 个；这不是 AFL/GCC 覆盖失败，应进入提示词、schema 或模型重试策略的修复队列。
- 本轮 union edge 为 299954，可作为后续 corpus admission 和趋势回归基线；单测例 `新增 edge` 为 0 的程序不一定无价值，但在入库优先级上应低于能增加 union edge 或具备强 oracle 的程序。
- gcov 源码覆盖率快照仍对应 260 个历史 covered corpus；当前 AFL covered 已为 471，源码覆盖率需按需重放后再更新。

## AFL edge map 统计

| 指标 | 数值 |
| --- | --- |
| covered programs | 471 |
| 本轮累计 union edge 数 | 299954 |
| 最小 edge map 条目 | 2590 |
| 最大 edge map 条目 | 106602 |
| 平均 edge map 条目 | 21235.5 |
| 中位 edge map 条目 | 3412.0 |

这些 edge map 条目来自 AFL++ instrumentation，不是 gcov 源码行覆盖率。`edge entries` 是单个测例触发的控制流边数量，`union edge` 是本轮所有 covered 测例触发的去重边集合。`union 占比` 表示某个测例单独覆盖了本轮 union edge 的多少；`新增 edge` 表示按表格顺序加入 corpus 时该测例带来的新增去重边数。

当前已有 gcov 源码覆盖快照，但它对应 260 个历史 covered corpus；当前 AFL covered 为 471。本轮优先评估 AFL feedback，不更新 gcov 汇报口径。

## 语言与 oracle 分布

| 语言 | GroupLLM ready | 本轮 InstanLLM |
| --- | --- | --- |
| ada | 1 | 0 |
| asm | 11 | 6 |
| c | 449 | 431 |
| c++ | 61 | 57 |
| cobol | 1 | 0 |
| d | 2 | 0 |
| fortran | 6 | 0 |
| other | 2 | 2 |
| shell | 2 | 0 |

| oracle kind | 数量 |
| --- | --- |
| assembly_scan | 108 |
| compile_failure | 25 |
| compile_success | 141 |
| compile_success_runtime_exit | 2 |
| differential | 23 |
| execute_differential | 3 |
| link | 5 |
| runtime_exit | 185 |
| unknown | 4 |

## 本轮程序明细

| candidate | language | status | edge entries | 新增 edge | union 占比 | source |
| --- | --- | --- | --- | --- | --- | --- |
| group-0001-0c4805f873ab | c | covered | 3389 | 3389 | 1.13% | group-0001-0c4805f873ab-c3e91e494c515b88.lasx_shuffle_xvldx_test.c |
| group-0002-391244b3a5a5 | c | covered | 3387 | 34 | 1.13% | group-0002-391244b3a5a5-af27f7825965c3d8.loongarch_feature_interplay_test.c |
| group-0003-0913e3e3f3bd | c | covered | 3343 | 6 | 1.11% | group-0003-0913e3e3f3bd-4fff5d4a663bd11f.loongarch_ice_combined.c |
| group-0004-827806713198 | c | covered | 48436 | 45406 | 16.15% | group-0004-827806713198-f21e5660029e06fe.sibcall_abi_padding_test.c |
| group-0005-07d7ec961d96 | c | covered | 3402 | 19 | 1.13% | group-0005-07d7ec961d96-3995527ff35fe72f.loongarch_bug_group.c |
| group-0008-9b3ffea126fb | c | covered | 10969 | 255 | 3.66% | group-0008-9b3ffea126fb-0ad3f985666fd778.loongarch_combined_bugs.c |
| group-0009-de11becdf0ee | c++ | covered | 3426 | 3384 | 1.14% | group-0009-de11becdf0ee-074f41c9f5982d53.loongarch_ice_test.cc |
| group-0010-92fb7029d82a | c | covered | 3357 | 3 | 1.12% | group-0010-92fb7029d82a-a0e30f47051025ac.loongarch_vector_round_shuffle_pick.c |
| group-0011-9268b3400021 | c | covered | 3389 | 5 | 1.13% | group-0011-9268b3400021-1394ad77e14c19af.loongarch_combined.c |
| group-0013-21f2fcd244d0 | c | covered | 17251 | 2763 | 5.75% | group-0013-21f2fcd244d0-98ad3cd2c1ddb66b.loongarch_vec_test.c |
| group-0014-eb55f2204699 | c | covered | 40257 | 4619 | 13.42% | group-0014-eb55f2204699-3c2ddd7100aa3157.test_128bit_shift_large_const.c |
| group-0015-eed89675e7a2 | c | covered | 3404 | 21 | 1.13% | group-0015-eed89675e7a2-4d35a92077ad8bdd.loongarch_vector_rounding.c |
| group-0016-fed9b0650eb5 | c | covered | 18620 | 2099 | 6.21% | group-0016-fed9b0650eb5-c3bd0d06cf8b5ccc.group_0016_test.c |
| group-0017-1534392225bf | c | covered | 52556 | 8283 | 17.52% | group-0017-1534392225bf-e8cc94742ea9280b.test_group_0017.c |
| group-0018-ee210b474afe | c | covered | 44153 | 3038 | 14.72% | group-0018-ee210b474afe-5097ec25f3575dbb.loongarch_ice_combine.c |
| group-0023-f6851481d876 | c | covered | 3348 | 0 | 1.12% | group-0023-f6851481d876-be45be22287f1596.test_lasx_simd.c |
| group-0024-1e4e0ae3bdf8 | c | covered | 3431 | 0 | 1.14% | group-0024-1e4e0ae3bdf8-64e63158c3626c01.lsx_combined_test.c |
| group-0026-677adba21106 | c | covered | 2626 | 7 | 0.88% | group-0026-677adba21106-83193461f1a53444.loongarch_ice_triggers.c |
| group-0028-2c0c7a7b367e | c | covered | 85959 | 29361 | 28.66% | group-0028-2c0c7a7b367e-d3f7013d37ee3e15.test_loongarch_opt.c |
| group-0030-30491d959663 | c | covered | 3378 | 0 | 1.13% | group-0030-30491d959663-2ae6a650bd537466.vector_shuffle_abi.c |
| group-0032-1c4e8fe9e883 | c | covered | 3391 | 0 | 1.13% | group-0032-1c4e8fe9e883-044e7baa6e85b24a.loongarch_inline_lsx_fp_test.c |
| group-0034-dae0859c28a0 | c | covered | 3390 | 1 | 1.13% | group-0034-dae0859c28a0-f835e6d4185ab5ba.loongarch_vec_ice_combined.c |
| group-0036-0e72d2cc9821 | c | covered | 3384 | 3 | 1.13% | group-0036-0e72d2cc9821-1292ad4cd62e2bb6.loongarch_multi_bug_test.c |
| group-0039-99e7421fda60 | c | covered | 3400 | 0 | 1.13% | group-0039-99e7421fda60-04134c548cb4ec97.lsx_vector_ice_test.c |
| group-0041-e097040f4fb4 | c | covered | 43873 | 972 | 14.63% | group-0041-e097040f4fb4-77070609ab372113.loongarch_combined_test.c |
| group-0045-6d124569400f | c | covered | 3383 | 0 | 1.13% | group-0045-6d124569400f-9466fec431f64c52.loongarch_switch_vector_bitclear_pic.c |
| group-0046-22a0ab4e1324 | c | covered | 3362 | 0 | 1.12% | group-0046-22a0ab4e1324-6df02cfa3e920c05.loongarch_wrong_code_test.c |
| group-0047-2c73f0545c88 | c | covered | 19374 | 606 | 6.46% | group-0047-2c73f0545c88-286c3ec443691de3.group-0047-test.c |
| group-0048-615d38fae775 | c | covered | 3390 | 3 | 1.13% | group-0048-615d38fae775-c75a0e4cd144ee26.test_simd_interaction.c |
| group-0050-e3832b4ed26f | c | covered | 3367 | 0 | 1.12% | group-0050-e3832b4ed26f-e1fb707dd7bed921.test_bitreverse_constmul.c |
| group-0051-63fb78ca5761 | c | covered | 3369 | 0 | 1.12% | group-0051-63fb78ca5761-05f6c72667b73b59.test_loongarch_0051.c |
| group-0052-10da070c7760 | c | covered | 3394 | 2 | 1.13% | group-0052-10da070c7760-df129c57caa7fd38.loongarch_multi_feature_test.c |
| group-0054-3565fea53771 | c | covered | 3385 | 0 | 1.13% | group-0054-3565fea53771-0edddb60e3276db6.loongarch_complex_test.c |
| group-0055-244a4131ecb0 | c | covered | 3315 | 11 | 1.11% | group-0055-244a4131ecb0-951c0ed308a9167e.gcc-loongarch-mixed-bitreverse-bitint-asm.c |
| group-0056-625929b42350 | c | covered | 3388 | 24 | 1.13% | group-0056-625929b42350-0eaaf7868d366236.pr0056_mod_rot_cond_perm_vect.c |
| group-0057-94d18e5fc56d | c | covered | 3377 | 0 | 1.13% | group-0057-94d18e5fc56d-d64f5216218ee239.test_loongarch_lsx_0057.c |
| group-0058-72933998ab6c | c | covered | 3374 | 1 | 1.12% | group-0058-72933998ab6c-b1a2e9221c979944.test_combined.c |
| group-0059-594044a563a5 | c | covered | 3371 | 0 | 1.12% | group-0059-594044a563a5-fcbff63877d6a3f2.loongarch_combined_test.c |
| group-0060-5b21dee8e76b | c | covered | 82701 | 8164 | 27.57% | group-0060-5b21dee8e76b-8d4d3d1b1d04e4c6.group_0060_test.c |
| group-0061-d2b82b388a86 | c | covered | 3347 | 0 | 1.12% | group-0061-d2b82b388a86-2578779fb71aa078.loongarch_rotate_shuffle_shift.c |
| group-0063-8397bc2ee5f1 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0064-434a6d6881df | c | covered | 60553 | 2217 | 20.19% | group-0064-434a6d6881df-289773a41a476393.loongarch_loops.c |
| group-0066-abf70aca6470 | c | covered | 3351 | 0 | 1.12% | group-0066-abf70aca6470-0c7c9bfcdd4316d7.loongarch_vector_mix.c |
| group-0067-4cbbc78ee355 | c++ | covered | 11395 | 7780 | 3.80% | group-0067-4cbbc78ee355-83b2350ee60db569.tls_cost_array.cc |
| group-0068-a13a3a9f4afc | c | covered | 72588 | 4623 | 24.20% | group-0068-a13a3a9f4afc-dd63af4713fc089c.loongarch_combined_test.c |
| group-0071-3a82e414d135 | c | covered | 19687 | 444 | 6.56% | group-0071-3a82e414d135-1e95f0fa64d7fd22.loongarch_trigger_0071.c |
| group-0072-9ea960f72efe | c | covered | 3395 | 1 | 1.13% | group-0072-9ea960f72efe-453d41274871874c.loongarch_combined_test.c |
| group-0073-56d141a52ab8 | c | covered | 98179 | 9352 | 32.73% | group-0073-56d141a52ab8-62ad702def06c38b.loongarch_stress_test.c |
| group-0074-b8d618c3b085 | c | covered | 3424 | 1 | 1.14% | group-0074-b8d618c3b085-bb8abf09077c91eb.test_large_frame.c |
| group-0075-47e8e0a8ca85 | c | covered | 3394 | 18 | 1.13% | group-0075-47e8e0a8ca85-745d573a53a40bba.loongarch_opt_test.c |
| group-0076-0b68f1dfa9e4 | c | covered | 3364 | 0 | 1.12% | group-0076-0b68f1dfa9e4-8bc5ca9687fccdb4.lsx_combined_test.c |
| group-0077-a5bf52c0d1b7 | c | covered | 10926 | 594 | 3.64% | group-0077-a5bf52c0d1b7-d6fccaba9af477cf.loongarch_target_compile_test.c |
| group-0079-1f52b45231a0 | c | covered | 3395 | 4 | 1.13% | group-0079-1f52b45231a0-23a73b362d00d47e.loongarch_lto_simd_test.c |
| group-0081-45b512391f68 | c | covered | 3367 | 0 | 1.12% | group-0081-45b512391f68-4dc0a5fa57c306f3.group0081_test.c |
| group-0082-1b9531ee35ff | c++ | covered | 3450 | 45 | 1.15% | group-0082-1b9531ee35ff-d4fb105b02fabc96.test.cc |
| group-0083-d2eca85af029 | c | covered | 3371 | 4 | 1.12% | group-0083-d2eca85af029-29eb62b3958be34d.group_0083_combined.c |
| group-0084-b638845cad35 | c | covered | 50752 | 360 | 16.92% | group-0084-b638845cad35-e7bb92ba5254fc64.test_combined_la664.c |
| group-0085-dbfe7bd71499 | c | covered | 3383 | 0 | 1.13% | group-0085-dbfe7bd71499-3e735d3809f8b7c4.loongarch_integrated_test.c |
| group-0086-05e5645f0866 | c | covered | 3378 | 0 | 1.13% | group-0086-05e5645f0866-c4f8af981ff6da96.group_0086_test.c |
| group-0087-189b58aa0e34 | c | covered | 3367 | 0 | 1.12% | group-0087-189b58aa0e34-5071d8ac31c634a0.loongarch_rtl_interaction.c |
| group-0088-463272b62f42 | c | covered | 3351 | 0 | 1.12% | group-0088-463272b62f42-4b3e59c4f65fa3a6.group_0088_test.c |
| group-0089-eed807e28fb6 | c | covered | 3343 | 0 | 1.11% | group-0089-eed807e28fb6-c354800f267f308e.group_0089_test.c |
| group-0090-bcccba99226c | c | covered | 50424 | 348 | 16.81% | group-0090-bcccba99226c-9168b4de3f36a288.loongarch_asm_modifiers_ice.c |
| group-0091-fefcf0a2d3ae | c | covered | 3415 | 30 | 1.14% | group-0091-fefcf0a2d3ae-160d3dc40cc58571.lsx_reduction_test.c |
| group-0092-deca9e052b20 | c | covered | 3375 | 2 | 1.13% | group-0092-deca9e052b20-27ba6d9ccff2ba8a.test.c |
| group-0094-b2d9a9e96ee0 | c | covered | 44324 | 515 | 14.78% | group-0094-b2d9a9e96ee0-33c4a615f7c56b18.loongarch_merge_ccp.c |
| group-0096-6c50db238aad | c | covered | 3368 | 1 | 1.12% | group-0096-6c50db238aad-11652198fb7c815f.loongarch_features.c |
| group-0098-c6d740c8b77c | c++ | covered | 3445 | 20 | 1.15% | group-0098-c6d740c8b77c-5ba4649217370fc8.tls_simd_floor.cc |
| group-0099-01e15c94875c | c | covered | 18242 | 171 | 6.08% | group-0099-01e15c94875c-3a65532167173d93.loongarch64_test.c |
| group-0100-f979f03c9c7b | c | covered | 3422 | 30 | 1.14% | group-0100-f979f03c9c7b-1499d46765ee63b5.test_combined.c |
| group-0103-04955c9b5a35 | c | covered | 73579 | 654 | 24.53% | group-0103-04955c9b5a35-aaf7e59ab4058529.group_0103.c |
| group-0104-1c0fa7f9fc7c | c++ | covered | 3426 | 5 | 1.14% | group-0104-1c0fa7f9fc7c-2a060baece3d48e2.test_group_0104.cc |
| group-0106-04c71752fd06 | c | covered | 3315 | 0 | 1.11% | group-0106-04c71752fd06-6bfc5b1b2ff3e279.loongarch_combined_test.c |
| group-0107-0614e2eb43b8 | c | covered | 66083 | 859 | 22.03% | group-0107-0614e2eb43b8-06d8cdb017af89bc.test_loongarch_carry_div_store.c |
| group-0108-03aea3be6f6e | c | covered | 3420 | 0 | 1.14% | group-0108-03aea3be6f6e-e943f0f0fed98d95.lasx_large_frame_lto_test.c |
| group-0109-69add1433b43 | c++ | covered | 3398 | 1 | 1.13% | group-0109-69add1433b43-801645a11f444a0d.group_0109_69add1433b43.cc |
| group-0111-6d07858ea670 | c | covered | 53045 | 509 | 17.68% | group-0111-6d07858ea670-eeaf7ba43300494b.group_0111_test.c |
| group-0116-97b6027caa66 | c | covered | 19254 | 199 | 6.42% | group-0116-97b6027caa66-6f8a07b54ecbb3f5.multi_target_regression.c |
| group-0117-d8dc60d81349 | c | covered | 65048 | 565 | 21.69% | group-0117-d8dc60d81349-cd77e71443dca01b.loongarch_pattern_test.c |
| group-0118-92ed2f61b145 | c++ | covered | 3379 | 32 | 1.13% | group-0118-92ed2f61b145-f48c6a0484a29949.test_random_loongarch.cc |
| group-0119-6c7de28738fc | c | covered | 10647 | 21 | 3.55% | group-0119-6c7de28738fc-ba71baebf65ef6bf.group_0119_test.c |
| group-0120-50fc51ef56f5 | c | covered | 74905 | 2039 | 24.97% | group-0120-50fc51ef56f5-3a6e8ed6b8ea7112.loongarch_bug_cluster.c |
| group-0121-c9620dfeb191 | c | covered | 80017 | 1707 | 26.68% | group-0121-c9620dfeb191-d3e7ca97237526da.combined_bitint_vector.c |
| group-0122-9d6e6d2eafdf | c | covered | 34383 | 51 | 11.46% | group-0122-9d6e6d2eafdf-ae26670342e5e734.test_group_0122.c |
| group-0123-d7d167885df0 | c | covered | 3379 | 3 | 1.13% | group-0123-d7d167885df0-032ecbf57bb0b4c9.group_0123_test.c |
| group-0124-34e18d2bf59f | c | covered | 78144 | 1885 | 26.05% | group-0124-34e18d2bf59f-c61024bedd536694.group_0124_34e18d2bf59f.c |
| group-0125-d953391414ce | c | covered | 3386 | 0 | 1.13% | group-0125-d953391414ce-55a39269ff6fac8f.loongarch_fp_vec_test.c |
| group-0128-7bb9a9990491 | c | covered | 3343 | 0 | 1.11% | group-0128-7bb9a9990491-ee6cebd29920bb64.loongarch_rtl_combine_vregs_test.c |
| group-0129-952f0a600edb | c | covered | 17187 | 77 | 5.73% | group-0129-952f0a600edb-ac508ec3d254a159.bug_trigger_set.c |
| group-0130-5894955ea17c | c++ | covered | 11460 | 99 | 3.82% | group-0130-5894955ea17c-4c268a43a2fb55e6.group-0130-5894955ea17c.cc |
| group-0131-c4690b132828 | c | covered | 3314 | 1 | 1.10% | group-0131-c4690b132828-11418b50587feb05.loongarch_combined_test.c |
| group-0133-42fbcee20dbf | c | covered | 17696 | 1033 | 5.90% | group-0133-42fbcee20dbf-d3fa50b002c82a19.lto_opt_oracle.c |
| group-0134-6afb42d58142 | c++ | covered | 3413 | 4 | 1.14% | group-0134-6afb42d58142-914d0887c5d4b5bc.tls_desc_musttail_zero_bitfield.cc |
| group-0135-6273305721d8 | c | covered | 10365 | 0 | 3.46% | group-0135-6273305721d8-1a1f08fedfacd2b1.combined_rtl_bugs.c |
| group-0136-692174877920 | c | covered | 61794 | 302 | 20.60% | group-0136-692174877920-bde21b2f8191683f.group-0136.c |
| group-0139-ce3fa5d94716 | c++ | covered | 3515 | 54 | 1.17% | group-0139-ce3fa5d94716-7ab15fa305129654.loongarch_lto_asan_lsx_lasx_test.cc |
| group-0141-60747dc2ecf8 | c | covered | 11186 | 5 | 3.73% | group-0141-60747dc2ecf8-1b8270d133f5aba3.loongarch_interaction_test.c |
| group-0142-4ff99e992f94 | c++ | covered | 3357 | 1 | 1.12% | group-0142-4ff99e992f94-4f59cc16331dd218.loongarch_mixed_test.cc |
| group-0145-6f6694d89941 | c | covered | 3375 | 0 | 1.13% | group-0145-6f6694d89941-9afa2ab58343267a.loongarch_rtl_interaction_test.c |
| group-0146-ff272143ba6e | c | covered | 17400 | 37 | 5.80% | group-0146-ff272143ba6e-96135235b1bba28c.loongarch_combined_0146.c |
| group-0147-21a964bebded | c | covered | 48645 | 358 | 16.22% | group-0147-21a964bebded-759047a1134a273a.group_0147_test.c |
| group-0151-d833c79310de | c | covered | 15439 | 57 | 5.15% | group-0151-d833c79310de-7784876f0ccbdca7.vector_shift_combine_ternary.c |
| group-0157-43f51e674b00 | c | covered | 21602 | 604 | 7.20% | group-0157-43f51e674b00-a660e1b321ddd012.loongarch_ice_combo_0157.c |
| group-0158-5cd3746b6a35 | c++ | covered | 3402 | 1 | 1.13% | group-0158-5cd3746b6a35-e204e3846c678032.vector_musttail_zwb.cc |
| group-0159-dff9210641a4 | c | covered | 3411 | 2 | 1.14% | group-0159-dff9210641a4-abd54d5002ace5fb.loongarch_asm_fcsr_pragma_imm.c |
| group-0162-50daf4e1625d | c | covered | 3367 | 1 | 1.12% | group-0162-50daf4e1625d-15a4cad77a6827d5.loongarch_simd_bitint_stack.c |
| group-0165-e71fdecf648d | c | covered | 3372 | 0 | 1.12% | group-0165-e71fdecf648d-7a113bbc3c35952b.test.c |
| group-0170-25730b2b76d8 | c | covered | 3362 | 2 | 1.12% | group-0170-25730b2b76d8-124c60d5aeefab84.test_bitint_extdce.c |
| group-0173-ebc70fe3418c | c | covered | 10440 | 0 | 3.48% | group-0173-ebc70fe3418c-f1417032ce0d15aa.loongarch_fp_signal_unwind.c |
| group-0174-8ad80e188e43 | c | covered | 67477 | 828 | 22.50% | group-0174-8ad80e188e43-4c9989c5532b3b85.test.c |
| group-0175-495d8ce50a41 | c | covered | 3343 | 0 | 1.11% | group-0175-495d8ce50a41-66876025baea9eb1.group_0175_test.c |
| group-0178-5f70e4758aa3 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0179-f4cd426cd4df | c | covered | 3338 | 0 | 1.11% | group-0179-f4cd426cd4df-2269c4bb606bcfad.combined_decimal_fixed_sign.c |
| group-0181-2adbdf2086ca | c | covered | 3290 | 0 | 1.10% | group-0181-2adbdf2086ca-a6127574fd9cc921.test.c |
| group-0184-732fc4aee0bb | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0186-d95327e53907 | c | covered | 40536 | 30 | 13.51% | group-0186-d95327e53907-69a968e2c14aa755.loongarch_const_mul_asm_avg.c |
| group-0188-67da4e37b430 | c | covered | 3408 | 0 | 1.14% | group-0188-67da4e37b430-4a0f9f6fe51380ad.loongarch_combined_bugs.c |
| group-0189-b14296f2ae8b | c | covered | 3348 | 0 | 1.12% | group-0189-b14296f2ae8b-d54302f1119e9cc7.loongarch_group_0189.c |
| group-0190-5f7761799dd3 | c | covered | 3388 | 1 | 1.13% | group-0190-5f7761799dd3-99b981d4d914150e.lasx_shuffle_extdce.c |
| group-0192-1feb8cce1a93 | c | covered | 61186 | 399 | 20.40% | group-0192-1feb8cce1a93-549f9110dd957b6b.group_0192_1feb8cce1a93.c |
| group-0196-3a0deb9fe66f | c | covered | 3343 | 0 | 1.11% | group-0196-3a0deb9fe66f-a46c9fc154d85bed.loongarch_rtl_interaction.c |
| group-0199-47a45403c382 | c | covered | 80018 | 2430 | 26.68% | group-0199-47a45403c382-1d0058451fcb501e.test_group_0199.c |
| group-0200-d8a0ce8d27c6 | c | covered | 22188 | 795 | 7.40% | group-0200-d8a0ce8d27c6-e41aa19e8c30e0f1.test_loongarch_vec_ivopts.c |
| group-0204-f0aa7586a826 | c++ | covered | 3400 | 0 | 1.13% | group-0204-f0aa7586a826-d490714c9aba4daf.group-0204-test.cc |
| group-0205-a4624d96594d | c | covered | 81552 | 2068 | 27.19% | group-0205-a4624d96594d-68f8da784d986bfe.loongarch_group_0205.c |
| group-0206-547db4b6a6fc | c++ | covered | 16685 | 5131 | 5.56% | group-0206-547db4b6a6fc-4270cbaa7f7f3db3.loongarch_combined_test.cc |
| group-0207-dd90715844fe | c | covered | 10384 | 3 | 3.46% | group-0207-dd90715844fe-2ee2f40086422448.test_partial_vec_extdce.c |
| group-0208-297cb3a0a365 | c | covered | 10388 | 0 | 3.46% | group-0208-297cb3a0a365-9afe0cb22c72fb79.test_loop_recip_vector.c |
| group-0209-0f927417a935 | c | covered | 3482 | 0 | 1.16% | group-0209-0f927417a935-c3fc2d082791b3eb.gcc_bug_group_0209_test.c |
| group-0211-548514205cfd | c | covered | 52533 | 54 | 17.51% | group-0211-548514205cfd-bb15b6df76593710.bitint_fp_shortcircuit.c |
| group-0212-1f438e41ad96 | c | covered | 70929 | 1297 | 23.65% | group-0212-1f438e41ad96-9c4d05f3a04af844.group_0212_test.c |
| group-0213-b5dc2f787258 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0214-a38e6de734fd | c | covered | 41756 | 117 | 13.92% | group-0214-a38e6de734fd-864f01d8007588e2.test.c |
| group-0215-dfbfe60b2a5a | c | covered | 3383 | 1 | 1.13% | group-0215-dfbfe60b2a5a-4243bf23af382342.lsx_ext_dce_combined.c |
| group-0219-150aadd38b6f | c | covered | 60388 | 381 | 20.13% | group-0219-150aadd38b6f-196a316ad39e79dc.group_0219_test.c |
| group-0220-dd6ed1456545 | c | covered | 3371 | 0 | 1.12% | group-0220-dd6ed1456545-4393807064138574.test_group_0220.c |
| group-0221-7abb62f21ecc | c | covered | 10839 | 71 | 3.61% | group-0221-7abb62f21ecc-8b36f5b46ba80349.loongarch_missed_opt_combined.c |
| group-0222-c0f5cd85bc8a | c | covered | 78944 | 1238 | 26.32% | group-0222-c0f5cd85bc8a-52d8ffb96b9fc3de.group_0222_c0f5cd85bc8a.c |
| group-0223-be3a6f0116f1 | c | covered | 3386 | 0 | 1.13% | group-0223-be3a6f0116f1-7ce5702bec17fe31.bug_combination_test.c |
| group-0227-04ceca108b8c | c | covered | 34588 | 6 | 11.53% | group-0227-04ceca108b8c-90d518165138b074.loongarch_macro_hardreg.c |
| group-0231-a293fcedf85c | c | covered | 10861 | 0 | 3.62% | group-0231-a293fcedf85c-3ebee6bc4344f301.bitint_cond_assign_mixed_arith.c |
| group-0232-dc8b4157117e | c++ | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0235-312796560b87 | c | covered | 3351 | 0 | 1.12% | group-0235-312796560b87-4922fcfeba57e9b1.loongarch_combined_test.c |
| group-0236-9905f524060f | c | covered | 3375 | 0 | 1.13% | group-0236-9905f524060f-2b03a593f0aa3efa.lsx_lasx_bitcopy_asm_goto.c |
| group-0239-2131a5b042ad | c | covered | 3392 | 0 | 1.13% | group-0239-2131a5b042ad-ba68115e3c4febe8.lsx_fixedpoint_test.c |
| group-0240-fb9488c18a6d | c | covered | 3331 | 5 | 1.11% | group-0240-fb9488c18a6d-125089408a562175.pr_group_0240.c |
| group-0245-7da9cc729c4a | c | covered | 3378 | 2 | 1.13% | group-0245-7da9cc729c4a-32b3d4af92936536.lsx_reorder_classify_bitrev.c |
| group-0249-62041777e7ac | c | covered | 3389 | 0 | 1.13% | group-0249-62041777e7ac-49a51ddda0486716.group_0249_test.c |
| group-0251-91d7de9a6514 | c | covered | 47773 | 669 | 15.93% | group-0251-91d7de9a6514-f1a8a4b2eca5e82f.shift_combine_test.c |
| group-0252-71bdeb7cb6ec | c | covered | 3351 | 0 | 1.12% | group-0252-71bdeb7cb6ec-1a561edbc93b64b4.test_vec_perm_alias.c |
| group-0256-fb8940359632 | c | covered | 57210 | 150 | 19.07% | group-0256-fb8940359632-dc59ebc325af2731.test.c |
| group-0257-fe0123fc88ed | c | covered | 3343 | 0 | 1.11% | group-0257-fe0123fc88ed-b46dcc721ff35fd5.lsx_combined_test.c |
| group-0260-da4e79c9ada9 | c | covered | 3341 | 33 | 1.11% | group-0260-da4e79c9ada9-4685b8724f0359ad.test_group_0260.c |
| group-0261-d0409f52ed2a | c | covered | 78126 | 1439 | 26.05% | group-0261-d0409f52ed2a-9d213dd5bb05026a.pr117608-116488-125291.c |
| group-0263-f26811ea1dfb | c | covered | 3367 | 0 | 1.12% | group-0263-f26811ea1dfb-185309ef8a0b5bd6.loongarch_combined_test.c |
| group-0264-1c5c46c8c616 | c++ | covered | 54971 | 35865 | 18.33% | group-0264-1c5c46c8c616-1ee5a37b28fceba5.loongarch_build_failure_test.cc |
| group-0266-f52db01b314f | c | covered | 56899 | 1130 | 18.97% | group-0266-f52db01b314f-fbf674e6b22e4250.loongarch_bitint_ice.c |
| group-0267-2312606076da | c | covered | 3302 | 0 | 1.10% | group-0267-2312606076da-cb6c5ee4512703af.sad_sibcall_signext.c |
| group-0269-fff855c40381 | c | covered | 64730 | 591 | 21.58% | group-0269-fff855c40381-44160f264abc81af.test_bug_0269.c |
| group-0270-7d91f299ef5a | c | covered | 3380 | 0 | 1.13% | group-0270-7d91f299ef5a-b6fbcf135eba3b12.loongarch_group_0270.c |
| group-0272-265010186dc0 | c | covered | 3343 | 0 | 1.11% | group-0272-265010186dc0-dde4e8808f44f9ff.loongarch_vector_combine_test.c |
| group-0274-89c70bffc35f | c | covered | 3359 | 0 | 1.12% | group-0274-89c70bffc35f-dc12de57d32c09e8.lsx_floor_cmp_test.c |
| group-0277-ef5bb1bb4d7a | c | covered | 3368 | 5 | 1.12% | group-0277-ef5bb1bb4d7a-3ff44166020d0856.test.c |
| group-0278-74e5b118ce56 | c | covered | 44983 | 650 | 15.00% | group-0278-74e5b118ce56-fb1711c98ffa7502.pr121413_96692_123635.c |
| group-0279-db5d6117651e | c | covered | 3395 | 0 | 1.13% | group-0279-db5d6117651e-29ea6f3521627577.loongarch_combined_test.c |
| group-0280-0cd5e9744e98 | c | covered | 3393 | 0 | 1.13% | group-0280-0cd5e9744e98-9497e0b56c7bfdf3.combined_loongarch_bugs.c |
| group-0283-d6b19851075b | c | covered | 12006 | 10 | 4.00% | group-0283-d6b19851075b-c314e8c11e7d8def.loongarch_pragma_scope_test.c |
| group-0284-cb6b51df3e7f | c | covered | 44110 | 80 | 14.71% | group-0284-cb6b51df3e7f-f46033011bba2667.pr117599.c |
| group-0285-954b72c7d525 | c++ | covered | 11446 | 5 | 3.82% | group-0285-954b72c7d525-9eff8f4cf4c16e32.group_0285_954b72c7d525_test.cc |
| group-0286-1c6fb29175d1 | c | covered | 10435 | 0 | 3.48% | group-0286-1c6fb29175d1-9fa18fde720b3d9a.gcc_loongarch_ice_test.c |
| group-0287-c21e85f9a4ac | c++ | covered | 11539 | 9 | 3.85% | group-0287-c21e85f9a4ac-e1fa3b20ca9cd2e1.group_0287_test.cc |
| group-0288-53a51b5b937d | c | covered | 3452 | 4 | 1.15% | group-0288-53a51b5b937d-358a3da40d5b6418.lsx_lasx_combined_test.c |
| group-0289-2e7508d2e7b6 | c | covered | 58273 | 181 | 19.43% | group-0289-2e7508d2e7b6-74ec12f8dc802c0e.loongarch_asm_frame_sext.c |
| group-0290-7352abfc6eb1 | c | covered | 19830 | 95 | 6.61% | group-0290-7352abfc6eb1-e2f7f4681d7d8301.test.c |
| group-0292-074bab91eedd | c++ | covered | 3488 | 3 | 1.16% | group-0292-074bab91eedd-cbffc50b568e9502.group-0292-074bab91eedd.cc |
| group-0293-e51311280030 | c | covered | 3398 | 0 | 1.13% | group-0293-e51311280030-f0d48c2e7a836e56.loongarch_bitfield_modulo_memcpy_test.c |
| group-0294-774ca5468a39 | c++ | covered | 41496 | 11543 | 13.83% | group-0294-774ca5468a39-32f7e09c4123f197.lto_dotprod_subreg.cc |
| group-0295-a5757b57e7f2 | c++ | covered | 3449 | 3 | 1.15% | group-0295-a5757b57e7f2-c02ebafb1befc534.group-0295-a5757b57e7f2.cc |
| group-0297-f26c4ca56e53 | c | covered | 19470 | 73 | 6.49% | group-0297-f26c4ca56e53-f913213c64f88267.loongarch_vec_test.c |
| group-0298-2dc40b27ee4f | c++ | covered | 3410 | 0 | 1.14% | group-0298-2dc40b27ee4f-a2d2263a049f3c86.loongarch_combined_test.cc |
| group-0299-7b2d5fd4d455 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0300-64b9939e6c1c | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0301-0bb7d03e72ca | c | covered | 74924 | 596 | 24.98% | group-0301-0bb7d03e72ca-457898afc326b14a.loongarch_combined_test.c |
| group-0303-265753bb5db5 | c | covered | 3399 | 0 | 1.13% | group-0303-265753bb5db5-4c7d0a05ebb79d16.combined_test.c |
| group-0305-adb8610e4820 | c | covered | 3414 | 0 | 1.14% | group-0305-adb8610e4820-35470ab457f1018d.test_loongarch_group.c |
| group-0309-6b1f156e02cd | c | covered | 71939 | 1668 | 23.98% | group-0309-6b1f156e02cd-d4ff7584b8ef06df.loongarch_combined_test.c |
| group-0311-1da742e5d24d | c | covered | 17339 | 123 | 5.78% | group-0311-1da742e5d24d-4d8b5243ab2e3123.carry_ext_dce_test.c |
| group-0312-a68c4451b12b | c | covered | 63549 | 89 | 21.19% | group-0312-a68c4451b12b-afc7fba4398a8d7e.loongarch_combined_test.c |
| group-0313-b5e1e13a5cf8 | c | covered | 3376 | 0 | 1.13% | group-0313-b5e1e13a5cf8-81c9d86958ef7df6.loongarch_vector_glue_test.c |
| group-0315-bd197ce7d2f8 | c | covered | 3347 | 0 | 1.12% | group-0315-bd197ce7d2f8-676ce82addc091ce.group_0315_simd_test.c |
| group-0320-07742f0dfbe5 | c | covered | 19328 | 27 | 6.44% | group-0320-07742f0dfbe5-c33ee3f8fbbfe1ae.loongarch_lasx_vector_ice.c |
| group-0321-10370a6981a2 | c | covered | 3372 | 0 | 1.12% | group-0321-10370a6981a2-af6755d6d8cb4062.loongarch_multi_bug.c |
| group-0322-4dffbeed31d4 | c | covered | 3375 | 0 | 1.13% | group-0322-4dffbeed31d4-34fc25c8e0fc1fd9.loongarch_multi_feature_test.c |
| group-0323-8b93bb1fd357 | c | covered | 50030 | 193 | 16.68% | group-0323-8b93bb1fd357-d817f91f2c64537f.loongarch_combined_asm_modulo.c |
| group-0324-6301f9f3df33 | c | covered | 3362 | 0 | 1.12% | group-0324-6301f9f3df33-8c2a6d318b2d6cbb.loongarch_codegen_interaction.c |
| group-0325-b4ee70f0a808 | c | covered | 3364 | 0 | 1.12% | group-0325-b4ee70f0a808-159b1271b8f12897.combined_opt_test.c |
| group-0326-d9ce14204dd0 | c | covered | 38368 | 8 | 12.79% | group-0326-d9ce14204dd0-1551c0f51c5de527.loongarch_asm_glue_test.c |
| group-0327-5393075f3dfe | c | covered | 59210 | 207 | 19.74% | group-0327-5393075f3dfe-7d6b34c976fdfd49.grp0327.c |
| group-0328-575f8e51c2e4 | c | covered | 3373 | 0 | 1.12% | group-0328-575f8e51c2e4-862571f8f359ecf3.test.c |
| group-0329-b88b58aba8c0 | c | covered | 3387 | 0 | 1.13% | group-0329-b88b58aba8c0-1a61512654056b35.loongarch_fpu_lasx_test.c |
| group-0330-0762bb115401 | c | covered | 45621 | 75 | 15.21% | group-0330-0762bb115401-a8e670d7f605e93a.loongarch_la664_test.c |
| group-0331-2d7e193004ab | c | covered | 3375 | 0 | 1.13% | group-0331-2d7e193004ab-64265a4572724fcd.loongarch_simd_lto_bitrev.c |
| group-0332-9f17f783bf71 | c | covered | 3374 | 0 | 1.12% | group-0332-9f17f783bf71-c748cc6ed7f74e57.loongarch_mixed_bugs.c |
| group-0333-2ad15e41d08e | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0334-6316748f38a2 | c | covered | 82144 | 1547 | 27.39% | group-0334-6316748f38a2-2223cf285aa3736d.test_0334.c |
| group-0335-70434d9ba268 | c | covered | 77510 | 435 | 25.84% | group-0335-70434d9ba268-3bac1b097d84aedd.group-0335-70434d9ba268.c |
| group-0336-85bf4fa5d890 | c | covered | 3292 | 0 | 1.10% | group-0336-85bf4fa5d890-cd3f863ad62f27f3.lasx_shift_vcond_test.c |
| group-0337-76d75a69c8d8 | c | covered | 10860 | 3 | 3.62% | group-0337-76d75a69c8d8-9da150aa30322f40.loongarch_mixed_opt_test.c |
| group-0341-106b17b09ec0 | c | covered | 3400 | 0 | 1.13% | group-0341-106b17b09ec0-32d6c4a41115e784.group_0341_test.c |
| group-0342-a96a08af0996 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0343-b93e559f4b89 | c | covered | 15739 | 25 | 5.25% | group-0343-b93e559f4b89-d6e9e2aca41df815.test_mux_rotate_ice.c |
| group-0344-c48b5f661c0b | c | covered | 59443 | 144 | 19.82% | group-0344-c48b5f661c0b-575b733d5ac05a3d.loongarch_combined_test.c |
| group-0345-83c2b63f9dd2 | c | covered | 62038 | 241 | 20.68% | group-0345-83c2b63f9dd2-8260154f9ceabbc7.loongarch_reload_vector.c |
| group-0346-64dc84984dcf | c | covered | 3362 | 0 | 1.12% | group-0346-64dc84984dcf-70460cc5fe891c93.vectorizer_combined_test.c |
| group-0347-7218f3c65014 | c++ | covered | 3373 | 0 | 1.12% | group-0347-7218f3c65014-0090ad1d3ba655b6.carry_chain_test.cc |
| group-0349-58d0cd9c256e | c | covered | 3367 | 0 | 1.12% | group-0349-58d0cd9c256e-5278ca3d9f215406.lsx_vector_ice_test.c |
| group-0350-921425bd301e | c | covered | 3375 | 0 | 1.13% | group-0350-921425bd301e-01048a76fa013b56.test_combined_lsx.c |
| group-0351-4e45024a247b | c++ | covered | 3433 | 1 | 1.14% | group-0351-4e45024a247b-d15f33ea6d00bcb7.loongarch_multi_bug_test.cc |
| group-0352-522be0e8844c | c | covered | 3343 | 0 | 1.11% | group-0352-522be0e8844c-ba6f36b47d84b117.loongarch_simd_test.c |
| group-0353-ea09d7b73ed4 | c | covered | 3302 | 1 | 1.10% | group-0353-ea09d7b73ed4-afd4b310b2443624.group_0353_test.c |
| group-0354-e948498ea0b7 | c | covered | 48850 | 311 | 16.29% | group-0354-e948498ea0b7-03cd25d7133a0d81.loongarch_integration_test.c |
| group-0355-ce71044bb13f | c | covered | 3350 | 0 | 1.12% | group-0355-ce71044bb13f-4a1d6cae8bcc8cd7.loongarch_vector_ops.c |
| group-0356-f45a13d03531 | c | covered | 3343 | 0 | 1.11% | group-0356-f45a13d03531-d1b83bda0a547751.lsx_vector_bugs.c |
| group-0359-e887d2ba2547 | c++ | covered | 39976 | 1502 | 13.33% | group-0359-e887d2ba2547-db00027863a1f887.loongarch_build_errors.cc |
| group-0360-61b7f0a7add8 | c++ | covered | 24647 | 2059 | 8.22% | group-0360-61b7f0a7add8-0777a92d308e749c.loongarch_mixed_regression.cc |
| group-0365-681786eb5e5d | c | covered | 3498 | 13 | 1.17% | group-0365-681786eb5e5d-9b76e01e9e504bcf.loongarch_combined_test.c |
| group-0367-43ad87ca8227 | c | covered | 3343 | 0 | 1.11% | group-0367-43ad87ca8227-e0cdbcca4d5728bb.loongarch_vector_ifcombine_zeroext.c |
| group-0368-6f9ebd07320f | c | covered | 3452 | 0 | 1.15% | group-0368-6f9ebd07320f-32b4cfe20f2d8580.lsx_vector_compare_diag.c |
| group-0373-5375c17201cd | c | covered | 3376 | 0 | 1.13% | group-0373-5375c17201cd-f4671118e0f1f41c.loongarch_rtl_pass_interactions.c |
| group-0376-50d13aa1e3dd | c | covered | 3428 | 0 | 1.14% | group-0376-50d13aa1e3dd-9a81f7861a55a1e2.loongarch_multi_feature_test.c |
| group-0377-545ce9aa6e5a | c | covered | 3359 | 0 | 1.12% | group-0377-545ce9aa6e5a-f7cd8421e0dd37be.lasx_vec_compare_shuffle_dot.c |
| group-0381-b9ce42977a84 | c | covered | 3379 | 0 | 1.13% | group-0381-b9ce42977a84-411947ed271d5921.loongarch_multi_feature_test.c |
| group-0382-688acf06a661 | c | covered | 3375 | 0 | 1.13% | group-0382-688acf06a661-f359ff749a62f438.lsx_lasx_combined_test.c |
| group-0383-a38026889c6f | c | covered | 77388 | 2848 | 25.80% | group-0383-a38026889c6f-5dd64ba8f29cfdfa.loongarch_ice_trigger.c |
| group-0389-151dc48541ae | c | covered | 3367 | 0 | 1.12% | group-0389-151dc48541ae-d142c7c38200f60a.lsx_lasx_combined_test.c |
| group-0390-5caa9ba78cbc | c | covered | 18990 | 35 | 6.33% | group-0390-5caa9ba78cbc-2ca352e1db62e551.loongarch_ice_test.c |
| group-0392-9de8c84c57bb | c | covered | 3406 | 0 | 1.14% | group-0392-9de8c84c57bb-b6f7a79be5ef1ecc.loongarch_combined_test.c |
| group-0393-0d7cebab5f38 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0397-7e9c9c66d0eb | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0400-9944af5e1b95 | c | covered | 3415 | 0 | 1.14% | group-0400-9944af5e1b95-c3e1cc6f370a2d60.loongarch_combined_bugs.c |
| group-0405-dcc691c594e5 | c | covered | 11086 | 2 | 3.70% | group-0405-dcc691c594e5-8b3cf449870c3819.test_combined.c |
| group-0406-3cc212ed34b9 | c | covered | 3343 | 0 | 1.11% | group-0406-3cc212ed34b9-3a8c8ad2358f3167.pr0406_vect_eh_abi.c |
| group-0412-7bca4aa1f0b0 | c | covered | 3369 | 0 | 1.12% | group-0412-7bca4aa1f0b0-cd34968082a6108f.test_group_0412.c |
| group-0414-cfaf284c2521 | c | covered | 3372 | 0 | 1.12% | group-0414-cfaf284c2521-9cf0ed25a2e700b8.group-0414.c |
| group-0420-e8598185ca48 | c | covered | 3387 | 0 | 1.13% | group-0420-e8598185ca48-382c499cecbf9834.loongarch_integrated.c |
| group-0424-a332f22691dc | c | covered | 3460 | 0 | 1.15% | group-0424-a332f22691dc-bc709db920cccc0d.lsx_cost_profile_test.c |
| group-0426-6cd7462ce0aa | c++ | covered | 3393 | 0 | 1.13% | group-0426-6cd7462ce0aa-b7385e146a9b97ca.loongarch_regression.cc |
| group-0427-fc13f81483d4 | c | covered | 3425 | 0 | 1.14% | group-0427-fc13f81483d4-0ead11fd24bc3e97.loongarch_multi_feature_checksum.c |
| group-0428-a1faabd05927 | c | covered | 3305 | 0 | 1.10% | group-0428-a1faabd05927-c2a996c03497360e.reg_vect_widen_test.c |
| group-0432-92a0845cabf8 | c | covered | 32011 | 2361 | 10.67% | group-0432-92a0845cabf8-3a6031d411b33844.loongarch_combined_bugs.c |
| group-0433-48b227c9ebe1 | c++ | covered | 82472 | 20263 | 27.49% | group-0433-48b227c9ebe1-277ccfbc6e3e1874.loongarch_wrongcode_test.cc |
| group-0436-9cacc3b17f37 | c | covered | 16165 | 29 | 5.39% | group-0436-9cacc3b17f37-17198c60eb78e6a3.loongarch_bug0436.c |
| group-0437-3d116cea05e6 | c++ | covered | 3403 | 0 | 1.13% | group-0437-3d116cea05e6-feaac0e9f70a46a6.group-0437-3d116cea05e6.cc |
| group-0440-40d4040e1f0b | c | covered | 10446 | 0 | 3.48% | group-0440-40d4040e1f0b-e28e1e238c6a1bbb.test_loongarch.c |
| group-0449-1b705eaf7746 | c | covered | 3393 | 1 | 1.13% | group-0449-1b705eaf7746-e4951e4961328ac8.combined_test.c |
| group-0456-e6c616916e0f | c | covered | 55474 | 315 | 18.49% | group-0456-e6c616916e0f-9cf530524932f054.loongarch_ext_dce_and_reloc.c |
| group-0457-c3b336cf0b30 | c | covered | 82380 | 1349 | 27.46% | group-0457-c3b336cf0b30-9208935fba27d866.loongarch_slp_ice_test.c |
| group-0458-fac4fa4205b7 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0460-933bff55a955 | c | covered | 62651 | 129 | 20.89% | group-0460-933bff55a955-1d541518e2e54102.group-0460-933bff55a955.c |
| group-0465-69a4d4bb4610 | c | covered | 3380 | 3 | 1.13% | group-0465-69a4d4bb4610-10bcee65f68ffedd.test_group_0465.c |
| group-0468-7629192b72aa | c | covered | 3364 | 0 | 1.12% | group-0468-7629192b72aa-b43431bafb65066a.bitint_mux_nan_test.c |
| group-0472-333323c70198 | c | covered | 66968 | 797 | 22.33% | group-0472-333323c70198-7bf0a45de669a965.bitint_expand_bool_warning.c |
| group-0476-06e622e087b7 | c | covered | 3367 | 0 | 1.12% | group-0476-06e622e087b7-b49a16bda5b9b5f3.group-0476.c |
| group-0478-d735eded410c | c | covered | 56002 | 61 | 18.67% | group-0478-d735eded410c-4d34f30a7cc93a7a.loongarch_group_test.c |
| group-0479-f9a1a4d88a32 | c | covered | 3442 | 0 | 1.15% | group-0479-f9a1a4d88a32-b4e1e50dd283af96.bug_combination.c |
| group-0480-4b4dede1bdbb | c | covered | 17681 | 97 | 5.89% | group-0480-4b4dede1bdbb-2dbf08e078d1fee4.test.c |
| group-0487-b76d3d891b12 | c | covered | 10849 | 0 | 3.62% | group-0487-b76d3d891b12-4d1241a48a437c8f.test_combined.c |
| group-0488-b608dba11bb3 | c | covered | 101427 | 3639 | 33.81% | group-0488-b608dba11bb3-9bf5e33a219763f7.loongarch_slp_builtin_shuffle_cost.c |
| group-0489-88e918e55a6a | c | covered | 43031 | 36 | 14.35% | group-0489-88e918e55a6a-efa86d8cb63cb542.loongarch_ice_trio.c |
| group-0490-5449339f832d | c | covered | 3392 | 0 | 1.13% | group-0490-5449339f832d-059d4cfc2dae461b.loongarch_combined_test.c |
| group-0491-abcf1d3e5379 | c | covered | 3403 | 0 | 1.13% | group-0491-abcf1d3e5379-9cfd9f34b0a49be3.combined_loongarch_tests.c |
| group-0492-b0998f6fc522 | c | covered | 68872 | 139 | 22.96% | group-0492-b0998f6fc522-f2543a2d76cec6aa.group_0492_b0998f6fc522.c |
| group-0529-a11a75c46ae8 | c | covered | 3389 | 0 | 1.13% | group-0529-a11a75c46ae8-be034624fa4dda9e.test_loongarch_vec_bitfield.c |
| group-0530-5a84eabc2cb8 | c | covered | 3379 | 0 | 1.13% | group-0530-5a84eabc2cb8-fc841087e8f8982b.loongarch_rtl_regression.c |
| group-0531-156cec5c0d07 | c | covered | 18005 | 23 | 6.00% | group-0531-156cec5c0d07-08c5b10e4d4bebf1.loongarch_interplay.c |
| group-0533-ddf43aaba425 | c | covered | 80099 | 157 | 26.70% | group-0533-ddf43aaba425-68fe2c7eb01ecbb7.test.c |
| group-0534-0faaf3313288 | c++ | covered | 24914 | 953 | 8.31% | group-0534-0faaf3313288-72ff39206adad314.group_0534_test.cc |
| group-0536-f05bee7b796f | c | covered | 3508 | 6 | 1.17% | group-0536-f05bee7b796f-f2237ea50553e6ba.lsx_diag_test.c |
| group-0537-fe61918e3310 | c | covered | 3375 | 0 | 1.13% | group-0537-fe61918e3310-254b8fd56654a0a9.test-0537.c |
| group-0538-e9a09166f242 | c | covered | 40384 | 8 | 13.46% | group-0538-e9a09166f242-5462910003dcb458.loongarch_asm_inline_test.c |
| group-0539-98f8ceaa9d33 | c | covered | 3366 | 3 | 1.12% | group-0539-98f8ceaa9d33-adbecca33e15e265.group-0539.c |
| group-0587-b763edc7d834 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0587-b763edc7d834 | c | covered | 3395 | 0 | 1.13% | group-0587-b763edc7d834-5166bf83bbd82fc3.la664_vector_sched_ivperm_test.c |
| group-0588-947576e6e0ab | c | covered | 3387 | 1 | 1.13% | group-0588-947576e6e0ab-8af8043444164fd0.group_0588_relax_snan_simd_sibcall.c |
| group-0588-947576e6e0ab | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0590-5af2b224a48a | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0591-fcd9a425d775 | c++ | covered | 80687 | 12154 | 26.90% | group-0591-fcd9a425d775-5ce0387d81d49fe0.kernel.cc |
| group-0592-22d6e7286dd3 | c | covered | 3407 | 3 | 1.14% | group-0592-22d6e7286dd3-dc03b22cf5f6ae4e.lsx_fcc_regress_0592.c |
| group-0593-b4df094a1482 | c | covered | 3407 | 1 | 1.14% | group-0593-b4df094a1482-b3a77ce17d79435e.loongarch_lto_vectorizer_convergence.c |
| group-0594-83e98c4fb60c | c | covered | 48508 | 143 | 16.17% | group-0594-83e98c4fb60c-db465ce53a35ba81.group-0594-83e98c4fb60c.c |
| group-0596-211cde6ad207 | c | covered | 57428 | 114 | 19.15% | group-0596-211cde6ad207-28f25baac75ee74d.group_0596.c |
| group-0597-cbce6edcc3e8 | c | covered | 3355 | 0 | 1.12% | group-0597-cbce6edcc3e8-334678366452e1b5.group-0597-cbce6edcc3e8.c |
| group-0598-e727b4ba2605 | c | covered | 3359 | 1 | 1.12% | group-0598-e727b4ba2605-1573008d3f382be4.group_0598_lsx_copysign_permute_ranger.c |
| group-0599-42078283844a | c | covered | 3420 | 1 | 1.14% | group-0599-42078283844a-c9149b9e652a48d7.group-0599-42078283844a.c |
| group-0600-c0d6b2b3ac7d | c++ | covered | 3425 | 3 | 1.14% | group-0600-c0d6b2b3ac7d-b77beb67a059d746.loongarch_mixed_opt_pipeline.cc |
| group-0601-5d0225f605ad | c | covered | 3377 | 0 | 1.13% | group-0601-5d0225f605ad-5510ef34e81e50e7.loongarch_subreg_reduction.c |
| group-0602-e73ee4c645a0 | c | covered | 67245 | 70 | 22.42% | group-0602-e73ee4c645a0-2ae7f0ee3f153490.loongarch_codegen_idioms.c |
| group-0603-2e8c64657caf | c | covered | 3383 | 0 | 1.13% | group-0603-2e8c64657caf-7e50234a2cd7aa72.loongarch_bitfield_vector_ivopts.c |
| group-0605-5ae0c72c1813 | c | covered | 3379 | 0 | 1.13% | group-0605-5ae0c72c1813-17599d5b700516fc.loongarch_pragma_inline_intrinsic_asm.c |
| group-0606-03d162ac8f5c | c | covered | 3474 | 5 | 1.16% | group-0606-03d162ac8f5c-d23479077fcda139.large.c |
| group-0607-17ca9046666f | c | covered | 3388 | 0 | 1.13% | group-0607-17ca9046666f-6addea524beec9f5.main.c |
| group-0608-3c344036447b | c | covered | 17975 | 33 | 5.99% | group-0608-3c344036447b-40f078455f3eedf8.fused_eh_snan_fmax_bool.c |
| group-0609-2560f5907bc8 | c++ | covered | 3454 | 0 | 1.15% | group-0609-2560f5907bc8-06f474e43d679670.loongarch_vec_musttail_carry_checksum.cc |
| group-0610-865cf66bb91f | c | covered | 3411 | 0 | 1.14% | group-0610-865cf66bb91f-b17d4d1ceafbc401.lasx_vec_coupling.c |
| group-0611-771ed3ddb16e | c | covered | 97001 | 1896 | 32.34% | group-0611-771ed3ddb16e-95d17f688ce17197.loongarch_ice_cluster_0611.c |
| group-0612-3ffe2795140c | c | covered | 3372 | 1 | 1.12% | group-0612-3ffe2795140c-6bf1561bab49798e.lsx_fenv_inexact.c |
| group-0614-5711bcd69e9c | c | covered | 106602 | 2191 | 35.54% | group-0614-5711bcd69e9c-ab94a446fcfae2aa.la664_loop_fusion_test.c |
| group-0615-cfac1e99edae | c | covered | 3391 | 0 | 1.13% | group-0615-cfac1e99edae-22409c41d9f430c5.lsx_group_0615.c |
| group-0616-d77fedc2677b | c | covered | 3385 | 0 | 1.13% | group-0616-d77fedc2677b-02bd2c1f8b19f22d.loongarch_bstrins_andn_mul_check.c |
| group-0617-5ab8c86e81ed | c | covered | 3407 | 0 | 1.14% | group-0617-5ab8c86e81ed-55d3e44f00ba492d.lsx_chain_0617.c |
| group-0618-7e89fea0f439 | c | covered | 39292 | 334 | 13.10% | group-0618-7e89fea0f439-a6374f5cc231a330.group-0618-7e89fea0f439.c |
| group-0619-36a51770068c | c++ | covered | 3440 | 1 | 1.15% | group-0619-36a51770068c-bbee3a18f1581eb6.tu.cc |
| group-0620-145974915f30 | c | covered | 55225 | 340 | 18.41% | group-0620-145974915f30-64e7628d891b8850.loongarch_rtl_trigger_0620.c |
| group-0621-e02bd9a94d00 | c | covered | 3419 | 3 | 1.14% | group-0621-e02bd9a94d00-5bfb526285ea1e09.lsx_lasx_sanitizer_check.c |
| group-0622-0ae0aa8c7b5e | c++ | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0623-b92efd2fc432 | c | covered | 3356 | 0 | 1.12% | group-0623-b92efd2fc432-bd63ecf9708d4516.group_0623_lasx_shuffle_atomic.c |
| group-0624-38e3fa1037bc | c | covered | 3388 | 0 | 1.13% | group-0624-38e3fa1037bc-a57ef552015efa99.group_0624_38e3fa1037bc.c |
| group-0625-8a68aada6e55 | c | covered | 3361 | 2 | 1.12% | group-0625-8a68aada6e55-da2538e2aab50e3d.group-0625-8a68aada6e55-1cd67054c1fbc182.c |
| group-0626-c88f36e3d68f | c | covered | 75671 | 611 | 25.23% | group-0626-c88f36e3d68f-7bddbb7a9c956021.loongarch_scalar_slp_mashup.c |
| group-0627-d1e9424cb9c4 | c | covered | 3387 | 0 | 1.13% | group-0627-d1e9424cb9c4-78cf38e034f79a9b.lsx_fcmp_mask_canary.c |
| group-0628-f483cbc10f2a | c | covered | 72782 | 177 | 24.26% | group-0628-f483cbc10f2a-3ed4aebf50f0f27d.loongarch_epilogue_probe.c |
| group-0629-2b0e884b9cb1 | c | covered | 3364 | 0 | 1.12% | group-0629-2b0e884b9cb1-e1d237b4fdfa30d8.group-0629-2b0e884b9cb1.c |
| group-0630-848cac96f6c6 | c | covered | 90559 | 451 | 30.19% | group-0630-848cac96f6c6-c50a982315824d3c.loongarch_cost_model_112936_112935_120476_114978.c |
| group-0631-4c0c2c03de9c | c | covered | 88648 | 616 | 29.55% | group-0631-4c0c2c03de9c-c46646c238cd9b03.loongarch_combined.c |
| group-0632-d493239a8cb4 | c++ | covered | 3398 | 0 | 1.13% | group-0632-d493239a8cb4-1ac740519ffc3897.lasx_simd_vecset_cost.cc |
| group-0633-72f44cf85678 | c++ | covered | 3444 | 4 | 1.15% | group-0633-72f44cf85678-268ff4ad30b4e001.lsx_omp_copysign_reduction.cc |
| group-0635-b9dbf2f5ebbd | c | covered | 3404 | 0 | 1.13% | group-0635-b9dbf2f5ebbd-2c0851a398b194ab.loongarch_vec_abi_relax_maskeqz.c |
| group-0636-b6aa4a1b9627 | c | covered | 58532 | 130 | 19.51% | group-0636-b6aa4a1b9627-bab8ab9a8855be8a.group-0636-b6aa4a1b9627.c |
| group-0638-95825f913504 | c | covered | 3413 | 0 | 1.14% | group-0638-95825f913504-980615451e95bff0.group_0638_95825f913504.c |
| group-0640-938b2c2fe011 | c | covered | 53284 | 58 | 17.76% | group-0640-938b2c2fe011-887c8e51a4d56313.loongarch_chain_0640.c |
| group-0641-6844018c6119 | c | covered | 3375 | 0 | 1.13% | group-0641-6844018c6119-51b966ce54544f2b.group-0641-6844018c6119.c |
| group-0643-d8147b17fe44 | c | covered | 10935 | 0 | 3.65% | group-0643-d8147b17fe44-dff014b687cb2a8f.group-0643-d8147b17fe44.c |
| group-0644-0bbbe1442e63 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0646-18669e719a1e | c | covered | 3385 | 0 | 1.13% | group-0646-18669e719a1e-e73cfaccc3402f16.group-0646-18669e719a1e.c |
| group-0648-79b51dbc0f38 | c | covered | 87428 | 544 | 29.15% | group-0648-79b51dbc0f38-bbe5d820bed7db81.loongarch_memcpy_overflow_bitreverse.c |
| group-0649-0178e17e0863 | c | covered | 87671 | 81 | 29.23% | group-0649-0178e17e0863-ec194669e0d406b6.group_0649_0178e17e0863.c |
| group-0650-c35e41c1dacd | c | covered | 3367 | 0 | 1.12% | group-0650-c35e41c1dacd-4d08cf245ad554aa.loongarch_rtl_group.c |
| group-0651-5692f04b9adc | c | covered | 3384 | 0 | 1.13% | group-0651-5692f04b9adc-71cd2f6142d87700.group-0651-5692f04b9adc.c |
| group-0653-98dba6a1ace3 | c | covered | 61193 | 428 | 20.40% | group-0653-98dba6a1ace3-e3611f8eadc614a7.group_0653_chain.c |
| group-0654-e0af768bb548 | c | covered | 44525 | 37 | 14.84% | group-0654-e0af768bb548-14123e4977f6f96f.group-0654-e0af768bb548.c |
| group-0656-64b87f4dd098 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0657-3b589ee2f0c2 | c++ | covered | 86637 | 6847 | 28.88% | group-0657-3b589ee2f0c2-dcbf01a8ffcbecc4.loongarch_sibcall_cmove_cost.cc |
| group-0658-30f37ff198f4 | c | covered | 3484 | 2 | 1.16% | group-0658-30f37ff198f4-0480204f1e4887df.loongarch_lsx_sarif_probe.c |
| group-0659-df9a722e1461 | c | covered | 3388 | 0 | 1.13% | group-0659-df9a722e1461-24fd6f068ed9b08e.loongarch_fpu_bstrins_eh_tune.c |
| group-0660-4dc3fb6040aa | c | covered | 62292 | 135 | 20.77% | group-0660-4dc3fb6040aa-03a08f3c9734da7a.loongarch_group_0660.c |
| group-0661-fc37fc73f8b0 | c | covered | 3352 | 0 | 1.12% | group-0661-fc37fc73f8b0-52d99be2a247cbae.lsx_lasx_widen_vecinit_regress.c |
| group-0662-1c98bddaaf34 | c | covered | 3367 | 0 | 1.12% | group-0662-1c98bddaaf34-0b52c9bd25350f05.group_0662_1c98bddaaf34.c |
| group-0664-ae980ef835c4 | c | covered | 3395 | 0 | 1.13% | group-0664-ae980ef835c4-332bff558061b7b5.group-0664-ae980ef835c4.c |
| group-0665-ee5ddd499c80 | c++ | covered | 3430 | 0 | 1.14% | group-0665-ee5ddd499c80-1a958b562a28cddb.loongarch_kernel_chain.cc |
| group-0666-caaa0b497161 | c++ | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0667-740f78162ea0 | c | covered | 77004 | 134 | 25.67% | group-0667-740f78162ea0-18d1a3cac4287a89.group-0667_boolean_multiply_or_unroll.c |
| group-0668-555944aabdd2 | c | covered | 3388 | 0 | 1.13% | group-0668-555944aabdd2-4c4e619214a05464.loongarch_lsx_relax_interplay.c |
| group-0669-01505faf5464 | c | covered | 3404 | 0 | 1.13% | group-0669-01505faf5464-c55b9f7cf6a7202c.group-0669-01505faf5464.c |
| group-0670-adbebfd6c8e5 | c | covered | 66360 | 187 | 22.12% | group-0670-adbebfd6c8e5-e91a3ddf67ceb45d.g0670_memcpy_atomic_eh_logical.c |
| group-0671-1380067e85b4 | c | covered | 3372 | 3 | 1.12% | group-0671-1380067e85b4-9619e96c7a7954e8.group-0671-1380067e85b4.c |
| group-0672-18c06bceba04 | c | covered | 3379 | 0 | 1.13% | group-0672-18c06bceba04-27ec232ecf4bf669.group-0672-18c06bceba04-41dee33291734066.c |
| group-0673-05f1176c312c | c | covered | 89680 | 221 | 29.90% | group-0673-05f1176c312c-82f5c2b3f5e076fc.group-0673-05f1176c312c.c |
| group-0674-458e21cff72e | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0675-8c9356820f91 | c | covered | 3376 | 0 | 1.13% | group-0675-8c9356820f91-0c6acd5e339c0eaf.loongarch_constraint_trio.c |
| group-0676-c18a13eaa913 | c | covered | 3397 | 0 | 1.13% | group-0676-c18a13eaa913-0d6d36eb5974b574.loongarch_fusion_probe.c |
| group-0677-0f9819a1c163 | c | covered | 30501 | 128 | 10.17% | group-0677-0f9819a1c163-87da6f0c5d14a4ce.lto_ssp_bitselect_driver.c |
| group-0678-fd5446937c64 | c | covered | 44657 | 83 | 14.89% | group-0678-fd5446937c64-78ace243e5a6dc58.loongarch_cliff_0678.c |
| group-0679-a9051ae9718f | c | covered | 3305 | 0 | 1.10% | group-0679-a9051ae9718f-8a91439c685fd0ee.group_0679_a9051ae9718f.c |
| group-0680-90b217c12a76 | c | covered | 3420 | 0 | 1.14% | group-0680-90b217c12a76-55c298efd64dcbac.lsx_inline_asan_compile_test.c |
| group-0681-458c2e6ec495 | c | covered | 86304 | 591 | 28.77% | group-0681-458c2e6ec495-d11989016f4c5143.group-0681-458c2e6ec495.c |
| group-0682-333391b9d89f | c | covered | 3399 | 0 | 1.13% | group-0682-333391b9d89f-9d34c06aeed0b0a3.group-0682-333391b9d89f.c |
| group-0683-22030639a9ed | c++ | covered | 69267 | 3502 | 23.09% | group-0683-22030639a9ed-89d3490261a3eb0e.loongarch_group_0683.cc |
| group-0684-d3403876d3da | c | covered | 3347 | 0 | 1.12% | group-0684-d3403876d3da-f30bd1cb88ba1187.group-0684-d3403876d3da.c |
| group-0685-42e2bf2b745f | c | covered | 3362 | 0 | 1.12% | group-0685-42e2bf2b745f-13c7e59ea05dcc48.group-0685-42e2bf2b745f.c |
| group-0686-e203644e658b | c | covered | 3377 | 0 | 1.13% | group-0686-e203644e658b-0bd693815a519599.loongarch_ice_cluster_0686.c |
| group-0687-a6c3362b497d | c | covered | 60207 | 5 | 20.07% | group-0687-a6c3362b497d-9e80b9d1adcf1132.group-0687-a6c3362b497d.c |
| group-0689-7c5de9bf1934 | c | covered | 80430 | 339 | 26.81% | group-0689-7c5de9bf1934-618fde25df2aa57c.group-0689-7c5de9bf1934.c |
| group-0690-4e1842d5022a | c | covered | 79409 | 231 | 26.47% | group-0690-4e1842d5022a-939e7172000d7db8.group_0690_loongarch_probe.c |
| group-0691-2e0ced62eac6 | c++ | covered | 2670 | 18 | 0.89% | group-0691-2e0ced62eac6-413e687fbeb87b6e.loongarch_group0691.cc |
| group-0692-735fabe916f0 | c | covered | 3415 | 0 | 1.14% | group-0692-735fabe916f0-dd38d00e4c8ef638.group-0692-735fabe916f0.c |
| group-0694-482a248cbb13 | c | covered | 3353 | 0 | 1.12% | group-0694-482a248cbb13-cdb14de431908f24.g0694_lsx_lasx_vector_regression.c |
| group-0695-b74e1e738bd9 | c | covered | 70495 | 98 | 23.50% | group-0695-b74e1e738bd9-07893bfaa17de4e7.loongarch_group_0695_test.c |
| group-0696-eb9695831ec7 | c++ | covered | 46444 | 1491 | 15.48% | group-0696-eb9695831ec7-1409e90fad60d7cc.loongarch_asan_musttail_openmp.cc |
| group-0697-9cb8bbe5288d | c | covered | 17642 | 159 | 5.88% | group-0697-9cb8bbe5288d-e3f9798563125127.loongarch_fixed_float128_switch.c |
| group-0698-b25ed480da5c | c | covered | 3387 | 0 | 1.13% | group-0698-b25ed480da5c-39519c8f1f983ec3.group_0698_lsx_lto_bstrins.c |
| group-0699-06bde02599ed | c | covered | 3391 | 0 | 1.13% | group-0699-06bde02599ed-6a16a982904183d9.loongarch_target_attr_lsx_asm.c |
| group-0700-d879015ad9b1 | c++ | covered | 3424 | 0 | 1.14% | group-0700-d879015ad9b1-e7bd699ce4d2c099.main_tu.cc |
| group-0701-4c2a6b7b9136 | c | covered | 10398 | 0 | 3.47% | group-0701-4c2a6b7b9136-73057929cbe07b26.loongarch_fp_abi_rsqrt_vector_test.c |
| group-0702-74dfec5f76b4 | c | covered | 3396 | 0 | 1.13% | group-0702-74dfec5f76b4-b699e027ec4594b6.group_0702_74dfec5f76b4.c |
| group-0703-496e8a0f8b9d | c | covered | 3415 | 0 | 1.14% | group-0703-496e8a0f8b9d-4c0c69e59a5d4db4.lsx_loongarch_group_0703.c |
| group-0704-ee225c7c8121 | c | covered | 3382 | 0 | 1.13% | group-0704-ee225c7c8121-f1ce0f67b8dfca12.loongarch_lasx_asan_asm_test.c |
| group-0705-4758a26ed639 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0706-cff047904f6c | c | covered | 79780 | 154 | 26.60% | group-0706-cff047904f6c-5c33dcd88d8822a1.loongarch_ice_chain_0706.c |
| group-0707-00e0c0ba414c | c | covered | 65815 | 818 | 21.94% | group-0707-00e0c0ba414c-e944df718a30eb24.loongarch_abi_sibcall_bitfield_merge.c |
| group-0708-a8dfc4fe54ab | c | covered | 3396 | 0 | 1.13% | group-0708-a8dfc4fe54ab-5b4d753106150950.pr113418-117599-112919-lsx-bitint-align.c |
| group-0709-d5a71c2674ef | c | covered | 3458 | 0 | 1.15% | group-0709-d5a71c2674ef-4aa7be6830a49838.lsx_carry_rotate_shuffle.c |
| group-0710-b447740255e0 | c | covered | 3386 | 0 | 1.13% | group-0710-b447740255e0-7c8fff2acca8db04.loongarch_vector_stress_0710.c |
| group-0711-f70ecf5af31d | c | covered | 3347 | 0 | 1.12% | group-0711-f70ecf5af31d-de1367a933edfc59.loongarch_nan_self_shuffle_matrix.c |
| group-0712-07c18c7e8c51 | c | covered | 3387 | 0 | 1.13% | group-0712-07c18c7e8c51-ce8445028e25ee43.loongarch_bitfield_orchestration.c |
| group-0713-74cb5f2b3770 | c | covered | 3385 | 0 | 1.13% | group-0713-74cb5f2b3770-6d90032d08a78b0e.loongarch_256bit_pipeline.c |
| group-0714-5a97bf8edbe5 | c | covered | 3381 | 0 | 1.13% | group-0714-5a97bf8edbe5-18e54488e31abf27.group-0714-5a97bf8edbe5.c |
| group-0715-045f0b4ab363 | c | covered | 3368 | 0 | 1.12% | group-0715-045f0b4ab363-5334b29fac0ea957.group-0715-045f0b4ab363.c |
| group-0716-db4118ba29ca | c | covered | 3391 | 0 | 1.13% | group-0716-db4118ba29ca-9c41a2b6b91dc097.loongarch_wrong_code_ensemble.c |
| group-0717-769268c208f8 | c | covered | 3383 | 1 | 1.13% | group-0717-769268c208f8-81bfeba49c890181.loongarch_eh_mul_bitrev_fenv.c |
| group-0718-db0066e04120 | c | covered | 3400 | 0 | 1.13% | group-0718-db0066e04120-3da2b22378441d9a.loongarch_rtl_lasx_stress.c |
| group-0719-4d5711698de2 | c | covered | 11223 | 1 | 3.74% | group-0719-4d5711698de2-df0af4ccb7d88cbd.loongarch_group_0719_4d5711698de2.c |
| group-0720-017221b52659 | c | covered | 3411 | 0 | 1.14% | group-0720-017221b52659-78952aff5a0bad8e.la664_0720_synth.c |
| group-0721-5d71166a312b | other | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0722-8e71295f65ff | c | covered | 3372 | 0 | 1.12% | group-0722-8e71295f65ff-d777d075f7fba671.group-0722-8e71295f65ff.c |
| group-0723-cc0db5888117 | c | covered | 3384 | 0 | 1.13% | group-0723-cc0db5888117-99737b1eb86256e1.loongarch_interaction.c |
| group-0724-555cb84d991d | c | covered | 67046 | 219 | 22.35% | group-0724-555cb84d991d-33dafe68503596cd.loongarch_regress_group_0724.c |
| group-0725-87fded70093b | c | covered | 3382 | 0 | 1.13% | group-0725-87fded70093b-401312a80f5f0b27.loongarch_group_0725.c |
| group-0726-6b9d79f97b13 | c++ | covered | 11193 | 0 | 3.73% | group-0726-6b9d79f97b13-07843b1baa68c0c6.tls_main.cc |
| group-0727-23ca9950c81b | c | covered | 3378 | 0 | 1.13% | group-0727-23ca9950c81b-f4467296fd74bfc7.group-0727-23ca9950c81b.c |
| group-0728-5759263dbb9e | c | covered | 3347 | 0 | 1.12% | group-0728-5759263dbb9e-fac23b3057eb18a6.loongarch_nan_shuffle_ehreturn.c |
| group-0729-0273f5bca172 | c | covered | 90635 | 256 | 30.22% | group-0729-0273f5bca172-0354c936cb7bc3d7.loongarch_group_0729.c |
| group-0730-620306b337f2 | c | covered | 3384 | 0 | 1.13% | group-0730-620306b337f2-ff3164c0fb9b3be0.loongarch_vector_copysign_hardreg_pressure.c |
| group-0731-3246956bd0d2 | c | covered | 3343 | 0 | 1.11% | group-0731-3246956bd0d2-f711c51b919eb97a.group_0731_lsx_chain.c |
| group-0732-ef0321981ad9 | c | covered | 3407 | 0 | 1.14% | group-0732-ef0321981ad9-70d40b2ca2f65cb6.group-0732-ef0321981ad9.c |
| group-0733-1f62aadf5ba6 | c | covered | 3393 | 0 | 1.13% | group-0733-1f62aadf5ba6-bf80c2c85ed4104d.group-0733-lasx-region.c |
| group-0735-57ae44286bf8 | c | covered | 10860 | 0 | 3.62% | group-0735-57ae44286bf8-ec0bb10a9fe05fb4.loongarch_crc_stack_sweep.c |
| group-0736-f6f0bf1a54a8 | c | covered | 48141 | 85 | 16.05% | group-0736-f6f0bf1a54a8-0962a5c6f3451539.group-0736-f6f0bf1a54a8.c |
| group-0737-53596f9727e4 | c | covered | 86836 | 430 | 28.95% | group-0737-53596f9727e4-8bb39dbb51e5522f.loongarch_bitint_slp_ice.c |
| group-0738-6cdcda54126f | c | covered | 3400 | 0 | 1.13% | group-0738-6cdcda54126f-600b443af3a43ef1.group_0738_combined_backend_stress.c |
| group-0739-8305fcf6d12d | c | covered | 10852 | 0 | 3.62% | group-0739-8305fcf6d12d-9754e4194cbb3364.group-0739-8305fcf6d12d.c |
| group-0741-a8284fbd93ff | c++ | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0742-3c412baf3e7e | c | covered | 3406 | 0 | 1.14% | group-0742-3c412baf3e7e-df2d95a9f2c6271f.group_0742_vector_chain.c |
| group-0743-713023cde462 | c | covered | 88698 | 445 | 29.57% | group-0743-713023cde462-557f9f379969f667.group_0743_713023cde462.c |
| group-0744-6f8b5b8ed3d7 | c++ | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0745-885aa3ce4059 | c | covered | 77259 | 64 | 25.76% | group-0745-885aa3ce4059-e024d13a18c67568.loongarch_bitmerge_crc_chain.c |
| group-0746-36ec0c931a1e | c | covered | 3384 | 0 | 1.13% | group-0746-36ec0c931a1e-bca625559fba6897.main_tu.c |
| group-0747-17f199ce2d37 | c | covered | 91825 | 346 | 30.61% | group-0747-17f199ce2d37-fe4f9109d5ab2ab8.group-0747-17f199ce2d37.c |
| group-0748-ae26049ac4c2 | c | covered | 3411 | 0 | 1.14% | group-0748-ae26049ac4c2-7ecdca075d32f3e6.group-0748-ae26049ac4c2.c |
| group-0749-813f10cf7b93 | c | covered | 3389 | 0 | 1.13% | group-0749-813f10cf7b93-b22cdcfd4044c788.group-0749-813f10cf7b93.c |
| group-0750-24b25a7ca0a1 | c | covered | 3385 | 0 | 1.13% | group-0750-24b25a7ca0a1-aedc5c4cb2d963aa.loongarch_lsx_group_0750.c |
| group-0751-4ca1906891bc | c | covered | 69017 | 271 | 23.01% | group-0751-4ca1906891bc-79ce70162fa735a7.loongarch_0751_stress.c |
| group-0752-2f63c27c15c6 | c | covered | 37557 | 26 | 12.52% | group-0752-2f63c27c15c6-e96203b554e5f8f6.valid.c |
| group-0753-7e22e6edd266 | c | covered | 3387 | 0 | 1.13% | group-0753-7e22e6edd266-be57d24440754e44.group-0753-7e22e6edd266.c |
| group-0754-38c913a27810 | c | covered | 78623 | 141 | 26.21% | group-0754-38c913a27810-98981d60d1c37b36.group-0754-carry_mod_cse.c |
| group-0755-1d246ebe4a0c | c++ | covered | 3433 | 0 | 1.14% | group-0755-1d246ebe4a0c-0fb5b1301c6e2c77.loongarch_lasx_masked_blend_cost_probes.cc |
| group-0756-d9a18a9bf1d3 | c | covered | 67560 | 59 | 22.52% | group-0756-d9a18a9bf1d3-619a9a8a2221d47e.loongarch_mixed_opt_probe.c |
| group-0758-bc1a4abae5c2 | c | covered | 11328 | 93 | 3.78% | group-0758-bc1a4abae5c2-9c7f5fe247772dfa.loongarch_fclass_relax_trigger.c |
| group-0759-e80209a741b8 | c | covered | 10849 | 0 | 3.62% | group-0759-e80209a741b8-aab7f0bf72bedf1d.loongarch_group_0759_test.c |
| group-0760-fb932a82b1da | c | covered | 3451 | 3 | 1.15% | group-0760-fb932a82b1da-c8d831066f471a84.main.c |
| group-0761-a88c0cc14ea8 | c | covered | 3388 | 0 | 1.13% | group-0761-a88c0cc14ea8-4d6f7f632ff06a17.group-0761-a88c0cc14ea8.c |
| group-0762-0272b782636f | c++ | covered | 11386 | 30 | 3.80% | group-0762-0272b782636f-c919be0f1ef6d069.loongarch_frecipe_musttail_section_bitcast.cc |
| group-0763-423d2ad78fe6 | c | covered | 16699 | 5 | 5.57% | group-0763-423d2ad78fe6-1251b9c1e1fea656.loongarch_reload_stress_0763.c |
| group-0764-f038f3ed2670 | c | covered | 36706 | 1 | 12.24% | group-0764-f038f3ed2670-b1ca67fd1d395cb6.group_0764_trigger.c |
| group-0765-a14d7d2555a4 | c | covered | 3382 | 0 | 1.13% | group-0765-a14d7d2555a4-9c3da0b67196b9fe.loongarch_rtl_stress_0765.c |
| group-0767-a10d66942649 | c | covered | 3380 | 0 | 1.13% | group-0767-a10d66942649-73a0c80276048c65.group-0767-a10d66942649.c |
| group-0768-bcc14431a156 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0769-038767a35914 | c | covered | 3405 | 0 | 1.14% | group-0769-038767a35914-6cd50c6f8a29f2f8.group_0769_lsx_range_chain.c |
| group-0770-31ab8ca4acc6 | c | covered | 3350 | 0 | 1.12% | group-0770-31ab8ca4acc6-d48c36bc869ffd49.group-0770-31ab8ca4acc6.c |
| group-0771-fc75b5e91e7c | c | covered | 85264 | 158 | 28.43% | group-0771-fc75b5e91e7c-02b75146f0ab432e.group-0771_fc75b5e91e7c.c |
| group-0772-c4e1015294fe | c | covered | 3350 | 0 | 1.12% | group-0772-c4e1015294fe-25d8ec75a4885c7c.loongarch_vector_stress_0772.c |
| group-0773-637d5e7af510 | c | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0774-ad064b155fc9 | c | covered | 3416 | 0 | 1.14% | group-0774-ad064b155fc9-abd039cde12927c0.group-0774-ad064b155fc9.c |
| group-0775-0b249fcc9d22 | c | covered | 3383 | 0 | 1.13% | group-0775-0b249fcc9d22-7c3f18be921a9bdd.group_0775_test.c |
| group-0776-6f9f60a4d04e | c | covered | 3394 | 1 | 1.13% | group-0776-6f9f60a4d04e-3b40b9d7fbb31e23.loongarch_stress_0776.c |
| group-0777-78725765d60e | c | covered | 58612 | 70 | 19.54% | group-0777-78725765d60e-aa5ec3d038214e08.group-0777-driver.c |
| group-0779-957381e48603 | c | covered | 3409 | 0 | 1.14% | group-0779-957381e48603-8a5eff8a4e085cb8.loongarch_combined_checks.c |
| group-0780-48a839a553d7 | c++ | covered | 3404 | 0 | 1.13% | group-0780-48a839a553d7-50bf34359e363b99.group-0780-48a839a553d7.cc |
| group-0781-510093b18823 | c | covered | 3412 | 0 | 1.14% | group-0781-510093b18823-7937d6a36535ebd9.main.c |
| group-0782-8d774f71d914 | c++ | covered | 11296 | 15 | 3.77% | group-0782-8d774f71d914-f6c8e5c89f7cfecf.group-0782-8d774f71d914.cc |
| group-0783-c1f571fb7350 | c | covered | 3380 | 0 | 1.13% | group-0783-c1f571fb7350-d7ab0bba218be941.g0783_loongarch_vec_fp_chain.c |
| group-0784-59a59428a51e | c | covered | 3400 | 2 | 1.13% | group-0784-59a59428a51e-f630d4f19eca3b5c.lasx_shuffle_sibcall_asm_align.c |
| group-0785-2cb57a0cd51b | c | covered | 11713 | 1 | 3.90% | group-0785-2cb57a0cd51b-60d9047d8d3ff7ae.group_0785_sqrt_ccp_snan.c |
| group-0786-e7dc2e6e8d6e | c | covered | 3412 | 0 | 1.14% | group-0786-e7dc2e6e8d6e-8a67a0724fefc71d.lsx_lasx_intrinsic_interplay.c |
| group-0787-008b45e0a4dc | c | covered | 38468 | 9 | 12.82% | group-0787-008b45e0a4dc-0bae4f7f12d357fd.mixedopt_ice_triad.c |
| group-0788-f4e9a1c84d4b | c | covered | 80452 | 79 | 26.82% | group-0788-f4e9a1c84d4b-5331b848052fde9b.group_0788_loongarch_fusion.c |
| group-0789-74fbbfce84a2 | c | covered | 3395 | 0 | 1.13% | group-0789-74fbbfce84a2-737ac7b01a84c593.group-0789-74fbbfce84a2.c |
| group-0790-c83a6bac2603 | c | covered | 2590 | 1 | 0.86% | group-0790-c83a6bac2603-c0f744998849b945.loongarch_codegen_group_0790.c |
| group-0791-467c3697db96 | c | covered | 3347 | 0 | 1.12% | group-0791-467c3697db96-23562de997ce4895.group_0791_lsx_lasx_shuffle_masks.c |
| group-0792-f117e4a17695 | c | covered | 84017 | 25 | 28.01% | group-0792-f117e4a17695-9ff0a8793e34f565.group-0792-f117e4a17695.c |
| group-0793-d877cd243703 | c | covered | 3378 | 0 | 1.13% | group-0793-d877cd243703-540f36a3da0a622b.loongarch_vshuf_perm_alias.c |
| group-0795-acad24d91dba | c++ | covered | 3378 | 0 | 1.13% | group-0795-acad24d91dba-ea6003689353358f.group-0795-acad24d91dba.cc |
| group-0796-462cc74b53a0 | c | covered | 3387 | 0 | 1.13% | group-0796-462cc74b53a0-5a6a688328fc8736.group-0796-462cc74b53a0.c |
| group-0797-e6f7e2537bfe | c | covered | 49409 | 180 | 16.47% | group-0797-e6f7e2537bfe-bf1b534b17b12e9e.loongarch_fixed_combiner_oversize_text.c |
| group-0798-79ee05b25fd1 | c | covered | 3353 | 0 | 1.12% | group-0798-79ee05b25fd1-8442a6cb315522dd.group-0798-vector-relax.c |
| group-0799-78fd7c0d3486 | c | covered | 3393 | 0 | 1.13% | group-0799-78fd7c0d3486-a2b7f89e73fafb58.group_0799_bitint_vecperm.c |
| group-0800-5538066d58a8 | c | covered | 51078 | 69 | 17.03% | group-0800-5538066d58a8-c646890d209ebeab.group-0800-5538066d58a8.c |
| group-0801-7aa333f67504 | c++ | covered | 3430 | 0 | 1.14% | group-0801-7aa333f67504-0905972d2d49e647.group-0801-7aa333f67504.cc |
| group-0802-35a85029be71 | c | covered | 3409 | 0 | 1.14% | group-0802-35a85029be71-9f0ff81124be3618.loongarch_multi_tu_regression.c |
| group-0803-d28c25d96389 | c | covered | 50980 | 24 | 17.00% | group-0803-d28c25d96389-45f4cc673cc4c4d3.test.c |
| group-0804-e8e8d6fec295 | c++ | skipped_not_ready | 0 | 0 | 0.00% |  |
| group-0806-477a36ceead5 | c | covered | 3305 | 0 | 1.10% | group-0806-477a36ceead5-48e6486c0b6cb945.loongarch_0806_regression.c |
| group-0807-2dfd33d31bb3 | c | covered | 3396 | 0 | 1.13% | group-0807-2dfd33d31bb3-911c43f6c0a6a200.lsx_compare_shuffle_bitfield_fmax.c |
| group-0808-d8d18cc532be | c | covered | 3372 | 0 | 1.12% | group-0808-d8d18cc532be-5c277649629753f9.group_0808_d8d18cc532be.c |
| group-0809-3e64d1b516fb | c | covered | 10375 | 0 | 3.46% | group-0809-3e64d1b516fb-8b1e965f32cf5332.loongarch_tune_triad.c |
| group-0810-1e2d4d94e4fb | c | covered | 3409 | 0 | 1.14% | group-0810-1e2d4d94e4fb-efb95b68ebb1210d.group_0810_fusion.c |
| group-0811-17ad0b1afad8 | c | covered | 10996 | 10 | 3.67% | group-0811-17ad0b1afad8-0216931dde6964ee.loongarch_mixed_bitfield_index_ice.c |
| group-0812-64399c04ea94 | c++ | covered | 3465 | 0 | 1.16% | group-0812-64399c04ea94-6021f9ba3f531f22.group-0812-64399c04ea94.cc |
| group-0813-f581b68a5113 | c | covered | 19122 | 57 | 6.37% | group-0813-f581b68a5113-a1df5a41a0d77ca8.gcc-loongarch-0813-combined.c |
| group-0814-33090c03ae50 | c | covered | 88735 | 773 | 29.58% | group-0814-33090c03ae50-2ba5163d934a1de2.loongarch_vector_fpu_stress_0814.c |
| group-0815-678250b2db27 | c | covered | 3403 | 1 | 1.13% | group-0815-678250b2db27-e518733c141b93d3.loongarch_vec_copysign_div_nan_kernel.c |
| group-0816-b8c6ad2b7907 | c | covered | 3361 | 0 | 1.12% | group-0816-b8c6ad2b7907-9877008bc5301906.group_0816_b8c6ad2b7907.c |
| group-0817-4aa7719fcb87 | c | covered | 67071 | 266 | 22.36% | group-0817-4aa7719fcb87-aee62c6bb28027e0.loongarch_group_0817.c |
| group-0818-4e842185f86e | c++ | covered | 11422 | 0 | 3.81% | group-0818-4e842185f86e-eaa947f6fcddb53e.loongarch_rtl_crc_earlyclobber_prng_stress.cc |
| group-0820-b9852a030fd3 | c | covered | 3365 | 0 | 1.12% | group-0820-b9852a030fd3-e916848ad9260297.group_0820_b9852a030fd3_test.c |
| group-0821-a18f13aadc9e | c++ | covered | 3444 | 2 | 1.15% | group-0821-a18f13aadc9e-591c1c02ab9a24da.pr117575_123643_125045_lasx_canary.cc |
| group-0822-e0ad45f68e1a | c | covered | 3367 | 0 | 1.12% | group-0822-e0ad45f68e1a-b48fd507fed92b82.group-0822-e0ad45f68e1a.c |
| group-0823-385f201634da | c | covered | 38568 | 31 | 12.86% | group-0823-385f201634da-ddc1bcac069eec5f.group-0823-385f201634da.c |
| group-0824-d3eab909aa6b | c | covered | 3375 | 0 | 1.13% | group-0824-d3eab909aa6b-9aa88b9bd1dbd691.loongarch_stress_0824.c |

## 当前边界与后续工作

- 当前 evaluator 直接复用 `scripts/afl-showmap-gcc.sh`，因此只对 C/C++ 调用 `cc1`/`cc1plus` 形成覆盖数据。
- Fortran/Ada/D/asm/RTL/shell/COBOL ready groups 并非无效，而是需要对应前端或专用 harness：例如 `f951`、GNAT、D frontend、assembler scan、RTL dump/compile pass 或 shell-driven multi-file harness。
- C/C++ ready groups 已完成全量 InstanLLM + AFL edge 评估，并已接入 gcov 源码行/函数覆盖重放。下一阶段应细化 oracle，并为 assembly-scan、diagnostic、Fortran/asm/RTL 分别实现 evaluator。
