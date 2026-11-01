# Reproducibility report

Scale: `full` | Seed: `20261022` | Result: **IDENTICAL: the dataset is reproducible**

Command, run twice into two separate folders: `python -m src.generate --scale full --seed 20261022`

## Row counts

| table | rows run A | rows run B | match |
|---|---|---|---|
| supplier | 20 | 20 | yes |
| instrument_type | 15 | 15 | yes |
| calibration_plan | 30 | 30 | yes |
| asset | 2000 | 2000 | yes |
| calibration_event | 5000 | 5000 | yes |
| certificate | 4893 | 4893 | yes |
| work_order | 5391 | 5391 | yes |
| audit_record | 23801 | 23801 | yes |
| alert | 1790 | 1790 | yes |
| production_use | 100000 | 100000 | yes |
| ground_truth | 160 | 160 | yes |

## SHA-256 checksums

| file | run A | run B | match |
|---|---|---|---|
| csv/alert.csv | `9269e35b6242a0126ee29a59ffd2c28c3c894e870e07327e9899fcc4b621b0b5` | `9269e35b6242a0126ee29a59ffd2c28c3c894e870e07327e9899fcc4b621b0b5` | yes |
| csv/asset.csv | `08d2792fdc3a6e1b6213101d062f241f6f5ad85fb61b7bf864bc02bd7bbfd752` | `08d2792fdc3a6e1b6213101d062f241f6f5ad85fb61b7bf864bc02bd7bbfd752` | yes |
| csv/audit_record.csv | `c10d57e62127ba3ac664c20fcf7f049f801335733549c6a41011c2d907666312` | `c10d57e62127ba3ac664c20fcf7f049f801335733549c6a41011c2d907666312` | yes |
| csv/calibration_event.csv | `4152196ab6143e5a140c2396c7c304b29de488fd5304ba1359393608e276c24a` | `4152196ab6143e5a140c2396c7c304b29de488fd5304ba1359393608e276c24a` | yes |
| csv/calibration_plan.csv | `df56e7cd068fce5cbba45808a75f71d9aa444e73be6cc4ac2104b5757dea9870` | `df56e7cd068fce5cbba45808a75f71d9aa444e73be6cc4ac2104b5757dea9870` | yes |
| csv/certificate.csv | `c58592194ed681af7daad91c530e688072bed7b42a865a0f5a9cb3b31c6a335a` | `c58592194ed681af7daad91c530e688072bed7b42a865a0f5a9cb3b31c6a335a` | yes |
| csv/instrument_type.csv | `e13d6de336df55b405ac310784b4b4ec002c50c7aaa2dfe1966d70282fac87de` | `e13d6de336df55b405ac310784b4b4ec002c50c7aaa2dfe1966d70282fac87de` | yes |
| csv/production_use.csv | `139013000be08eb860557c52ce5a9bf8349a7d21338c27dd32e7fa7e23c8d35a` | `139013000be08eb860557c52ce5a9bf8349a7d21338c27dd32e7fa7e23c8d35a` | yes |
| csv/supplier.csv | `76bbca1b0cadda7b229273a912c3177cf0acbe268d2b57b01248e21e914a578f` | `76bbca1b0cadda7b229273a912c3177cf0acbe268d2b57b01248e21e914a578f` | yes |
| csv/work_order.csv | `765d61a792b79702ecbb4e0ef628443778fe3884cb19b2a1f0914075d7e37d6f` | `765d61a792b79702ecbb4e0ef628443778fe3884cb19b2a1f0914075d7e37d6f` | yes |
| dataset_manifest.json | `58028e8918582bd90b73800220d524bfb3d2a39b816923af83d9e8b629f6edd4` | `58028e8918582bd90b73800220d524bfb3d2a39b816923af83d9e8b629f6edd4` | yes |
| ground_truth/ground_truth.csv | `a4b4658213aa1fda0577a8f443fa16d4d87ed451f90eef51b555817cda5ba0b9` | `a4b4658213aa1fda0577a8f443fa16d4d87ed451f90eef51b555817cda5ba0b9` | yes |
| ground_truth/ground_truth.json | `81ea859dded384fe1dc8f1de71dfb0025adb3952b3d4e2f46dbf599b9499dc10` | `81ea859dded384fe1dc8f1de71dfb0025adb3952b3d4e2f46dbf599b9499dc10` | yes |
| json/alert.json | `263deda4c08c83577e4302a12393a6f3a3a032f2f07fdb07e9c5b799e288cc02` | `263deda4c08c83577e4302a12393a6f3a3a032f2f07fdb07e9c5b799e288cc02` | yes |
| json/asset.json | `120e605ade77f9fbea8d5429b815050ced9a5aa00a982457dbaa969de770af2e` | `120e605ade77f9fbea8d5429b815050ced9a5aa00a982457dbaa969de770af2e` | yes |
| json/audit_record.json | `c2c5daa984fdead3575c74aba25fa3b2020c7025433c53daf2f274a9e27c7c48` | `c2c5daa984fdead3575c74aba25fa3b2020c7025433c53daf2f274a9e27c7c48` | yes |
| json/calibration_event.json | `7abc0056c1446d83073dbd3213f3886256b0f0d0894ace6b0f726f3dd2b38e80` | `7abc0056c1446d83073dbd3213f3886256b0f0d0894ace6b0f726f3dd2b38e80` | yes |
| json/calibration_plan.json | `f0574e177ef58ae1e57fd4f9945dae720375a4655239e763219b7653dba7bda6` | `f0574e177ef58ae1e57fd4f9945dae720375a4655239e763219b7653dba7bda6` | yes |
| json/certificate.json | `73ff207350bfa5abf2572d4098e023a46999f4c888a2d71f242980deb4d15505` | `73ff207350bfa5abf2572d4098e023a46999f4c888a2d71f242980deb4d15505` | yes |
| json/instrument_type.json | `612c99ccff33d0404b0fe60bf33f83558df5133f2e276c0ec5fce12764687834` | `612c99ccff33d0404b0fe60bf33f83558df5133f2e276c0ec5fce12764687834` | yes |
| json/production_use.json | `31868b8205460f3924b9366e9998e75ba7af8a941b8f7afdaf78bc3e5056c2b7` | `31868b8205460f3924b9366e9998e75ba7af8a941b8f7afdaf78bc3e5056c2b7` | yes |
| json/supplier.json | `c26790d5749d8adb5b76bc179bd488dee61dbebc0aec4c619d1ae93db876aa93` | `c26790d5749d8adb5b76bc179bd488dee61dbebc0aec4c619d1ae93db876aa93` | yes |
| json/work_order.json | `f5bbedbf5e24e9df5fa53b073422b76e740d6dcbdb749ccd8f9d174bc2bb9a2c` | `f5bbedbf5e24e9df5fa53b073422b76e740d6dcbdb749ccd8f9d174bc2bb9a2c` | yes |
| reports/metrics.json | `6f3247888d7682700e25d01da7704d519382669302e77bf1a16889cbccd7e0a0` | `6f3247888d7682700e25d01da7704d519382669302e77bf1a16889cbccd7e0a0` | yes |
| reports/validation_summary.md | `6763428f9e02f51b41b568d3936dd42aad69991f6aba1fd6a8e40b28acf779f8` | `6763428f9e02f51b41b568d3936dd42aad69991f6aba1fd6a8e40b28acf779f8` | yes |
| source_manifest.json | `e6c9f9bae444e752959e0252fc2889e5e86759aa5e99f20eb67e929369280e27` | `e6c9f9bae444e752959e0252fc2889e5e86759aa5e99f20eb67e929369280e27` | yes |
| sql/schema.sql | `021ff9b6729225f3387594569c04a0227045816af8d40a14372db888e819cb67` | `021ff9b6729225f3387594569c04a0227045816af8d40a14372db888e819cb67` | yes |
| sql/seed.sql | `5ac530f669a8155c7b8f66881b78ce76ed3ce562ae776b86250d349dafb1909f` | `5ac530f669a8155c7b8f66881b78ce76ed3ce562ae776b86250d349dafb1909f` | yes |
