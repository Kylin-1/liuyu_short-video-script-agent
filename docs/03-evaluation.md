# 效果评估

## 环境与证据类型

本地测试环境为 Python 3.12。测试资料为合成产品及活动素材。评估按离线运行、协议测试和外部模型运行分别记录。

| 验证层 | 实际结果 | 证据 |
| --- | --- | --- |
| 自动测试 | 116 项通过 | [测试日志](../examples/test-results.txt) |
| 离线 CLI | 45 组结果符合预期，覆盖成功、追问、复核和失败状态 | [输入、输出与 Trace](../examples/INDEX.md) |
| 全角色协议 | 3 条路径通过；使用预设模型响应 | [协议记录](../examples/protocol-results.json) |
| HTTP 接入 | 本机服务验证请求、响应解析和角色编排 | [接口测试](../tests/test_requirements.py) |
| 外部模型 | BLOCKED，未配置端点和模型，调用次数为0 | [预检记录](../examples/live/acceptance.json) |

离线及协议测试验证程序行为；真实模型决策与创作效果尚未完成验证，当前未形成两条外部模型动态路径记录。

## 验收用例

| 场景 | 预期 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 正常生成 | 完整中文脚本，引用和检查齐全 | 带货23秒、到店23秒、活动24秒 | [核心用例与输入](../examples/REVIEW.md) |
| 缺关键信息 | 生成前追问 | NEEDS_INPUT | [Trace](../examples/runs/creative_missing.trace.json) |
| 无素材 | 同主体补检或请求资料 | MATERIAL_REQUIRED | [Trace](../examples/runs/creative_no_material.trace.json) |
| 工具失败 | 记录错误，有限重试后停止 | TOOL_FAILED | [Trace](../examples/runs/creative_tool_failure.trace.json) |
| 超时修订 | 根据估时改稿并复检 | 带货23→13秒 | [输入](../examples/inputs/campaign_short.txt) · [Trace](../examples/runs/creative_short.trace.json) |
| P01字幕功能 | 保留「支持字幕」依据并满足上限 | 26→14秒，引用P01 | [脚本](../examples/runs/p01_duration.output.md) · [Trace](../examples/runs/p01_duration.trace.json) |
| 时长无法满足 | 明确失败 | DURATION_UNMET | [Trace](../examples/runs/creative_impossible.trace.json) |
| 必说项有依据 | 补写后重新检查 | 22→26秒，增加活动条件原文 | [Trace](../examples/runs/raw_disclosure_repaired.trace.json) |
| 必说项缺依据 | 停止并定位问题 | QUALITY_FAILED | [Trace](../examples/runs/raw_rule_blocked.trace.json) |
| 同输入换空库 | 下一步动作随检索结果改变 | 请求同主体素材 | [Trace](../examples/runs/same_input_empty_catalog.trace.json) |
| 预算耗尽 | 返回未完成状态 | TOOL_LIMIT | [Trace](../examples/runs/tool_budget.trace.json) |

全部案例的原始输入、实际输出和运行记录见 [结果索引](../examples/INDEX.md)。

## 约束与对抗测试

| 验证点 | 测试结果 |
| --- | --- |
| 无依据重量与防漏主张 | 离线来源检查拦截；可修改参考文案经替换、复检后交付 |
| 新剧情与有据改写 | 角色协议案例保留新开场；同义改写附素材原文进入交付结果 |
| 审核报告完整性 | 漏字段、重复、改写待核原文、无效引用均被拒绝 |
| 导演修改边界 | 重写台词、漏镜头、乱序、压缩时降低同动作下限均被拒绝 |
| 定向返修 | 事实、转化入口、锁定创意和非目标字段保持受保护 |
| 角色异常 | 各角色失败均返回 MODEL_FAILED |
| 品牌规则输入 | 必说项生效；未知键与跨来源规则冲突明确报错 |
| 检查版本 | 修改后重新检查；过期报告无法授权交付 |
| 任务隔离 | 复用客户端时清空上下文和调用计数 |

测试实现见 [角色测试](../tests/test_llm_studio.py)、[来源测试](../tests/test_grounding.py) 和 [可靠性测试](../tests/test_reliability.py)。

## 流程开销与创作对照

协议测试的正常、时长修订、事实返修路径分别发生15、19、21次模型适配器调用。调用计数来自实际程序运行；响应由测试替身提供，外部服务延迟和费用未测量。

[同输入对照](../examples/creative-comparison.md) 比较 legacy 与 planned 在相同需求、素材和规则下的开场、状态、时长、工具调用及步骤。人工评价表支持开场、因果、商品融入、结尾和可拍性五个维度，目前尚未收集评分。

## 已知限制

| 项目 | 当前限制 | 后续验证 |
| --- | --- | --- |
| 外部模型 | 供应商兼容性、JSON稳定性及生成效果未测 | 正常、超时、空素材及故障四条真实路径 |
| 语义事实审核 | 引文校验能检查出处；语义支持仍依赖模型判断 | 人工标注主张及引文，统计误放行与误拦截 |
| 离线自由文案 | 保守来源检查会将部分合法对白转入复核 | [误拦样例](../examples/runs/valid_custom_deferred.output.json) |
| 时长 | 基于文本和镜头预算估算 | 试读或TTS校准 |
| 创作效果 | 未开展人工盲评或投放评价 | 同素材、同目标的盲评对照 |
| 结构修改 | 返修保持镜头编号、顺序和引用 | 评估需要增删镜头的重构场景 |
| 输入与制作范围 | 中文标签文本及JSON；下游成片制作另行处理 | 根据使用场景扩展解析与制作接口 |
| 运行环境 | 本地验证Python 3.12，CI配置3.11/3.12/3.13 | 执行远程CI矩阵 |

`raw_production`、`raw_tutorial`、`raw_brief`、`raw_reference_p01` 的锁定文案在当前离线模式下返回 NEEDS_REVIEW，详见结果索引。

## 复现命令

```bash
python -X utf8 examples/run_examples.py
python -X utf8 examples/run_live_acceptance.py
```

第二条命令需要配置模型环境变量；缺少配置时保留 BLOCKED 记录。
