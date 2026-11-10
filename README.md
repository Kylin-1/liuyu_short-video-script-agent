# 中文短视频脚本 Agent

项目地址：[https://github.com/Kylin-1/27-_-_AIAgent-_-04-](https://github.com/Kylin-1/27-_-_AIAgent-_-04-)

本项目面向商品带货、到店引流、活动推广等创作场景，将制作需求、产品素材和品牌规则转化为可编辑的中文分镜脚本。系统通过制片人、编剧、导演和审核角色协作，在生成过程中执行素材检索、时长估算及规则检查，并依据检查结果补充检索、修改脚本、请求资料或结束任务。

项目采用 Python 原生实现，提供 CLI、离线 Mock 和 Chat Completions 兼容模型接口。多角色架构借鉴 AutoGen 的角色分工、消息传递和工具反馈思路，由原生状态机承载角色编排和运行控制。重点是事实可追溯、基于工具反馈的决策，以及修订后重新验证。

[快速运行](#快速运行) · [脚本示例](#脚本示例) · [架构与决策](#架构与决策) · [测试与验证](#测试与验证) · [设计文档](#设计文档)

## 快速运行

环境要求：Python 3.11+。仅使用标准库，无需安装第三方依赖。以下命令均在仓库根目录执行；Windows 可将 `python` 替换为 `py -3`。

```bash
# 离线生成中文脚本，并保存完整执行记录
python -X utf8 -m src.main examples/inputs/raw_intent_story.txt --model mock --trace story.trace.json

# 输出可编辑的 JSON
python -X utf8 -m src.main examples/inputs/raw_intent_story.txt --model mock --json

# 单独查看标准化需求、来源和待确认事项
python -X utf8 -m src.main examples/inputs/raw_intent_story.txt --brief-only

# 执行自动测试
python -X utf8 -m unittest discover -s tests -v
```

默认输出 Markdown。成功退出码为 `0`；缺资料、未完成或失败为 `2`，具体原因由 `status` 和检查结果说明。只有 `status=COMPLETED` 时，`script` 才包含最终脚本；中间稿保留在 Trace 中。

## 脚本示例

以下均使用合成素材，通过离线 Mock 实际运行生成。

| 场景 | 原始需求 | 脚本 | 运行记录 |
| --- | --- | --- | --- |
| 商品带货：出门前确认杯盖锁扣 | [输入](examples/inputs/raw_intent_story.txt) | [23 秒脚本](examples/runs/creative_sales.output.md) | [Trace](examples/runs/creative_sales.trace.json) |
| 到店引流：柜台该出示哪一页 | [输入](examples/inputs/campaign_store.txt) | [23 秒脚本](examples/runs/creative_store.output.md) | [Trace](examples/runs/creative_store.trace.json) |
| 活动推广：确认场次后预约 | [输入](examples/inputs/campaign_event.txt) | [24 秒脚本](examples/runs/creative_event.output.md) | [Trace](examples/runs/creative_event.trace.json) |
| 字幕功能推广：素材 P01 仅说明「支持字幕」 | [输入](examples/inputs/campaign_p01.txt) | [14 秒脚本](examples/runs/p01_duration.output.md) | [26→14 秒修订](examples/runs/p01_duration.trace.json) |

脚本包含标题、逐镜动作、旁白或字幕、起止时间、预计总时长、素材 ID 与原文、拍摄说明及风险。对应的 `.output.json` 可用于继续编辑；`.trace.json` 记录决策和工具执行过程。

[核心验收用例](examples/REVIEW.md) 覆盖正常生成、缺关键信息、无素材、工具失败和超时修订/失败；[完整结果索引](examples/INDEX.md) 收录全部离线用例。

## 输入与输出

支持 `.txt`、`.md` 和 JSON。文本输入使用三个区块：`【制作需求】`、`【素材】`、`【品牌规则】`。完整样例见 [原始制作需求](examples/inputs/raw_intent_story.txt)。

| 输入部分 | 主要内容 |
| --- | --- |
| 制作需求 | 主题、受众、平台、目标时长、风格，以及商业目标、内容形式、画幅 |
| 转化要求 | 转化动作和承接入口，例如点商品卡、到店领券、活动预约 |
| 素材 | ID、主体、事实原文、操作、可见画面和来源 |
| 品牌规则 | 禁用词、必须出现的内容，或明确说明无额外规则 |

需求整理会保留字段来源，检查缺失、歧义和冲突。商业目标与内容形式分开建模：同一购买目标可以采用演示或剧情形式。开场、转折和结局不是必填项，由编剧创作；显式提供的创意默认锁定，标为「创意要求策略：仅供参考」后允许定向修改。

JSON 请求包支持 `brief_text`、`material_notes`、`brand_notes` 及可选的 `confirmed`。也可直接传标准字段 JSON，通过 `--materials` 和 `--rules` 指定素材与规则文件。品牌规则 JSON 支持 `banned_terms`、`required_terms`，未知字段或规则冲突会报错。

文本请求只使用本次提供的素材。标准字段 JSON 为兼容离线演示，在未指定 `--materials` 时使用 `data/materials.json`。

## 架构与决策

主流程为：需求整理 → 素材检索 → 创意方案 → 方案选择 → 脚本创作 → 分镜规划 → 工具检查 → 制作与创作审核 → 输出。

系统参考 AutoGen 的多 Agent 协作方式：每个角色拥有独立职责、提示和结构化消息，制片人根据其他角色及工具的返回继续选择动作。原生 Python 状态机负责合法动作、稿件版本和调用预算，使角色协作与业务约束在同一执行链路中完成。

| 角色或模块 | 职责 |
| --- | --- |
| 制片人 | 读取当前状态与工具结果，选择查询、方案、修订、追问、停止或交付 |
| 编剧 | 提出最多两个创意方向，生成脚本，并根据反馈修改指定字段 |
| 导演 | 规划景别、动作、声音、转场、连续性和镜头时间 |
| 素材工具 | 按同一主体、查询词和可选素材 ID 检索，返回原文及来源 |
| 时长与规则工具 | 计算口播、字幕和画面预算，检查禁用词、必说项及部分显式主张 |
| 事实审核 | 区分虚构情境与产品主张，逐字段核对素材支持情况 |
| 制作与创作审核 | 检查引用、入口、可拍性、因果、节奏、商品融入和结尾兑现 |

在 `llm` 模式下，制片人每一步都会调用模型，编剧、导演及审核也分别使用独立角色提示调用模型。模型选择动作后，代码执行对应工具或角色，再将结果送入下一轮决策。本地状态机限制合法动作，负责契约、预算和交付校验。

主要反馈路径：

- **检索为空**：改写同主体查询，或请求补充素材。
- **估时超标**：修改可编辑文案或镜头停留时间，再次估时；无法满足时明确失败。
- **规则或事实问题**：在有依据且允许修改时定向返修，随后重新检查；否则停止或请求复核。
- **创作问题**：评审引用具体原句并提出修改目标，编剧保留事实和入口，仅修改目标字段。

目标时长是上限。已在上限内的脚本不会因为“越短越好”继续压缩；导演调整停留时间时保留同一动作的时长下限。

默认最多执行 **20 步、10 次业务工具调用、2 轮修订**。每次修改使旧版本检查失效；最终交付要求所有适用检查对应当前版本。Trace 包含步骤、工具入参、返回结果、下一步动作和简短决策依据，不记录模型内部思维。

## 模型配置

默认 `--model mock`，无需密钥，用于离线复现。`--model llm` 使用真实 HTTP 适配器，要求服务兼容 Chat Completions 请求和响应格式。

| 环境变量 | 含义 |
| --- | --- |
| `STUDIO_LLM_URL` | 完整请求端点，例如 `https://your-provider.example/v1/chat/completions` |
| `STUDIO_LLM_MODEL` | 服务支持的模型名称 |
| `STUDIO_LLM_KEY` | 服务所需的 API Key；通过 Bearer 认证发送 |

配置模板见 [.env.example](.env.example)。变量须在运行 shell 中设置，程序不会自动加载 `.env`。

```bash
# 使用模型生成，并保存逐角色调用和决策记录
python -X utf8 -m src.main examples/inputs/raw_intent_story.txt --model llm --trace model.trace.json

# 执行正常、超时、空素材和工具故障四条模型验收路径
python -X utf8 examples/run_live_acceptance.py
```

各角色共用一个端点和模型，以独立提示和任务上下文分工。接口要求模型返回符合契约的纯 JSON，单次超时为 20 秒，响应上限为 128 KiB。调用失败或响应不合约时返回 `MODEL_FAILED`，不会回退 Mock。真实创作使用 `planned` 模式；`legacy` 仅作为离线模板对照。

## 测试与验证

| 验证层 | 当前结果 | 证据 |
| --- | --- | --- |
| 自动测试 | 116 项通过 | [测试日志](examples/test-results.txt) |
| 离线 CLI | 45 组结果符合预期，含成功、追问与失败状态 | [结果索引](examples/INDEX.md) |
| 全角色协议 | 3 条路径通过，模型响应由测试替身提供 | [协议记录](examples/protocol-results.json) |
| HTTP 接入 | 本机测试服务验证请求、响应解析与全角色编排 | [接口测试](tests/test_requirements.py) |
| 外部真实模型 | 尚未执行；预检为 `BLOCKED` | [验收状态](examples/live/acceptance.json) |

重新生成离线输出、Trace、协议记录和测试日志：

```bash
python -X utf8 examples/run_examples.py
```

上述测试的预期、实际结果、失败案例及外部模型验证状态见 [效果评估](docs/03-evaluation.md)。

## 设计取舍

项目使用数据契约与有界状态机组织角色调用。模型负责创作、判断及动作选择，确定性代码负责数据结构、引用、时长计算和执行预算。产品主张附素材依据，人物情境由创作角色组织；返修以具体问题字段为单位，重新检查后再输出。

技术实现见 [方案文档](docs/02-solution.md)，接口与状态码见 [接口说明](docs/07-interface.md)。

## 设计文档

| 文档 | 内容 |
| --- | --- |
| [需求说明](docs/01-requirements.md) | 用户、目标、范围与成功标准 |
| [技术方案](docs/02-solution.md) | 总体架构、选型依据、角色定义、数据契约、调用流程与动态决策 |
| [效果评估](docs/03-evaluation.md) | 测试预期、结果、失败与限制 |
| [AI 使用说明](docs/04-ai-usage.md) | AI 辅助范围、个人贡献和验证方式 |
| [项目复盘](docs/05-retrospective.md) | 迭代问题、设计认识与后续计划 |
| [视频案例分析](docs/06-video-to-brief.md) | 从成片结构提炼 Brief 与分镜设计思路 |
| [接口与输出](docs/07-interface.md) | 模型接口、结果字段、状态码和 Trace |

目录职责：`src/` 为源码；`tests/` 为可执行测试；`examples/` 为输入、实际输出和 Trace；`data/` 为合成素材与规则；`docs/` 为设计与评估文档。
