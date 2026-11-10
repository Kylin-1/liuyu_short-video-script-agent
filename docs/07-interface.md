# 接口与输出说明

## 模型接口

接口使用 Chat Completions 兼容协议：HTTP POST 请求包含 `model` 与 `messages`，按配置添加 Bearer 认证。响应从 `choices[0].message.content` 读取 JSON 对象。

| 配置 | 用途 |
| --- | --- |
| STUDIO_LLM_URL | 完整请求端点 |
| STUDIO_LLM_MODEL | 模型名称 |
| STUDIO_LLM_KEY | 服务认证密钥 |

配置方式见 [README](../README.md#模型配置)。各角色共用端点，分别传入任务提示和结构化上下文。传输限制为20秒单次超时与128 KiB响应上限。

## 角色响应

| 任务 | 主要响应 |
| --- | --- |
| producer | action、reason、查询词或方案ID等适用参数 |
| plan | 1至2个创意方案、主证据、创作假设和字段来源 |
| write / rewrite / shorten | 标题及完整Beat列表 |
| direct | beat_id、计划时长、动作下限、构图、声音、转场、连续性 |
| grounding | 每个字段的原文、判断、依据和引用 |
| review / critique | 通过状态、问题定位和修改建议 |

响应由契约校验后进入状态；解析失败、缺字段或越出修改边界时返回 MODEL_FAILED。

## CLI结果

默认输出中文 Markdown，`--json` 输出结构化结果，`--trace` 保存完整执行过程。

| 字段 | 含义 |
| --- | --- |
| status / status_text | 任务状态及中文说明 |
| model_mode / creative_model_mode | 决策与创作实现模式 |
| script | 完成状态下的最终脚本 |
| checks | 当前稿件的时长、规则、来源和审核结果 |
| creative | 方案、选择原因、证据包和创作修订记录 |
| audit | 运行ID、计数、预算和输入摘要 |

脚本逐镜包含动作、旁白、字幕、时间区间、素材引用、字段依据和拍摄说明。风险项保留录制前试读、素材画面确认及内容复核事项。

## 状态处理

| 状态 | 含义 |
| --- | --- |
| COMPLETED | 当前版本检查通过，返回最终脚本 |
| NEEDS_INPUT | 制作需求需要补充或确认 |
| MATERIAL_REQUIRED | 需要补充素材 |
| NEEDS_REVIEW | 存在尚未解决的内容依据问题 |
| DURATION_UNMET | 无法满足时长上限 |
| QUALITY_FAILED | 规则或审核未通过 |
| MODEL_FAILED / TOOL_FAILED | 模型或工具失败 |
| STEP_LIMIT / TOOL_LIMIT / REVISION_LIMIT | 执行预算耗尽 |
| INVALID_INPUT / INVALID_ACTION | 输入或动作无效 |

完成状态退出码为0，其他任务状态退出码为2。

## Trace

Trace 按步骤记录动作、参数、工具调用与返回、后续动作、简要依据和稿件版本。`model_calls` 记录角色、模型、传输方式、耗时及请求/响应摘要。`decision_source` 标识动作来源。

接口测试记录、外部服务状态及覆盖范围统一见 [效果评估](03-evaluation.md)。
