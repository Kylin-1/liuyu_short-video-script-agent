# 核心验收入口

运行模式：**离线 Mock**。下表关联输入、实际输出和 Trace；`status=COMPLETED` 的 `script` 为最终脚本。验证范围见 [效果评估](../docs/03-evaluation.md)。

| 必验场景 | 原始输入 | 实际输出 | 运行记录 | 预期与实测 |
| --- | --- | --- | --- | --- |
| 正常生成 | [需求](inputs/raw_intent_story.txt) | [最终脚本](runs/creative_sales.output.md) / [JSON](runs/creative_sales.output.json) | [Trace](runs/creative_sales.trace.json) | COMPLETED，23秒 |
| 缺关键信息 | [需求](inputs/missing_input.json) | [结果](runs/creative_missing.output.json) | [Trace](runs/creative_missing.trace.json) | NEEDS_INPUT，生成前追问 |
| 无素材 | [需求](inputs/no_material.json) | [结果](runs/creative_no_material.output.json) | [Trace](runs/creative_no_material.trace.json) | MATERIAL_REQUIRED |
| 工具失败 | [需求](inputs/tool_failure.json) | [结果](runs/creative_tool_failure.output.json) | [Trace](runs/creative_tool_failure.trace.json) | TOOL_FAILED，注入检索故障 |
| 超时修正 | [需求](inputs/campaign_short.txt) | [结果](runs/creative_short.output.json) | [Trace](runs/creative_short.trace.json) | 23→13秒，COMPLETED |
| 超时无法满足 | [需求](inputs/impossible.json) | [结果](runs/creative_impossible.output.json) | [Trace](runs/creative_impossible.trace.json) | DURATION_UNMET |
| P01只支持字幕 | [需求](inputs/campaign_p01.txt) | [最终脚本](runs/p01_duration.output.md) / [JSON](runs/p01_duration.output.json) | [Trace](runs/p01_duration.trace.json) | 26→14秒，无效果数据承诺 |
| 无依据参考文案返修 | [需求](inputs/attack_weight_reference.txt) | [最终脚本](runs/attack_weight_reference.output.md) | [Trace](runs/attack_weight_reference.trace.json) | 去除未核验重量，复检交付 |

更多营销脚本： [到店引流](runs/creative_store.output.md) · [活动推广](runs/creative_event.output.md)。

[全部45组结果](INDEX.md) · [116项测试日志](test-results.txt) · [三条全角色协议测试](protocol-results.json) · [真实服务验收状态](live/acceptance.json)。

复现全部离线材料：`python -X utf8 examples/run_examples.py`。工具失败用例额外设置 `--fail-tool search_material --fail-times 2`；其他用例、模式和预算见 run_examples.py 的显式用例表。
