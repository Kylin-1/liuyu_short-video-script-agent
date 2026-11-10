# 从成片倒推制作简报

本文基于公开制作说明、作品档案及转录分析短视频的叙事组织，并将观察转化为本项目的 Brief 与分镜设计。时间码以引用转录为依据；制作需求列为本项目的分析结论。

## Google Pixel《Javier in Frame》

| 成片段落 | 可核对的内容 | 倒推的制作需求 |
| --- | --- | --- |
| 约 00:07–00:13 | 手机提示人脸被裁掉，引导调整手机位置。随后确认构图并响起快门声。 | 先出现具体问题，接着保留指令、操作和结果的因果顺序。证明点是拍下了照片，声音也能提供完成信号。 |
| 约 00:16–00:40 | 拍摄对象从独处及宠物逐步变为两人。同一类取景提示在多段生活场景中重复。 | 以人物生活变化组织场景，同一个功能反复出现时，每次都要推进故事。 |
| 约 00:46–00:52 | 提示从两张脸变成三张脸，随后是快门与婴儿哭声。 | 用新结果呼应开场。保留关键声画，即使压缩也尽量保住完成提示。 |

[Google 官方制作说明](https://blog.google/products-and-platforms/devices/pixel/superbowl-ad-2024-watch-javier-in-frame/) · [官方成片](https://www.youtube.com/watch?v=wYPTZIFQoDQ) · [带时间码转录](https://adinception.com/commercial/google-electronics-phones-javier-in-frame-google-pixel-sb-commercial-2024-commercial-ad-creative-united-states-wyptzifqodq)

## Apple《Don't Let Me Go》

| 成片段落 | 可核对的内容 | 倒推的制作需求 |
| --- | --- | --- |
| 起手 | 人物选中照片，准备删除。 | 把抽象的存储问题变成一个可观察的动作。开场说明具体发生什么。 |
| 中段 | 照片中的人物以歌声回应，劝拍摄者保留它们。 | 明确什么由声音承担，什么由屏幕画面承担。使用拟人化时让它服务同一个冲突。 |
| 结尾 | 手指离开删除图标，人物转而拍狗。 | 用与开场相反的动作表现决定变化。容量事实仍应由产品资料支持。 |

[D&AD 作品档案](https://www.dandad.org/work/d-ad-awards-archive/dont-let-me-go) · [成片报道](https://www.macrumors.com/2024/03/18/apple-iphone-15-storage-ad/)

## 对应的系统设计

| 观察 | 设计落点 |
| --- | --- |
| 具体动作建立观看期待 | 编剧方案包含人物目标、阻碍、开场和结尾兑现 |
| 操作与结果形成因果关系 | 素材分别记录操作、可见画面和事实原文，导演保持连续性 |
| 声音与画面共同表达结果 | 分镜包含声音、转场与连续性字段 |
| 结尾回应开场 | 创作评审检查人物行动与结尾是否对应 |
| 产品信息嵌入叙事 | 产品主张绑定素材引用，人物情境单独记录 |

对应的合成用例包括 [商品带货](../examples/inputs/raw_intent_story.txt)、[到店引流](../examples/inputs/campaign_store.txt) 和 [活动推广](../examples/inputs/campaign_event.txt)。运行结果见 [核心验收用例](../examples/REVIEW.md)。
