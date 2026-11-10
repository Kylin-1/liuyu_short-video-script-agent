# 项目提交信息

项目地址：[https://github.com/Kylin-1/liuyu_short-video-script-agent](https://github.com/Kylin-1/liuyu_short-video-script-agent)

项目名称：中文短视频脚本 Agent  
提交题目：第 04 题——短视频脚本 Agent  
运行方式：Python CLI

## 评审入口

| 内容 | 文件 |
| --- | --- |
| 环境、安装与运行命令 | [README.md](README.md) |
| 需求、范围与成功标准 | [docs/01-requirements.md](docs/01-requirements.md) |
| 架构选型、角色分工与动态决策 | [docs/02-solution.md](docs/02-solution.md) |
| 测试结果、失败案例与限制 | [docs/03-evaluation.md](docs/03-evaluation.md) |
| AI 辅助范围与个人贡献 | [docs/04-ai-usage.md](docs/04-ai-usage.md) |
| 核心输入、输出与 Trace | [examples/REVIEW.md](examples/REVIEW.md) |

## 快速验证

```bash
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m src.main examples/inputs/raw_intent_story.txt --model mock --trace story.trace.json
```

测试与示例结果均已保存在 `examples/`，外部模型接入方式见 README 的“模型配置”章节。
