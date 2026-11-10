# 创作流程对照

运行模式：离线 Mock。对照保持输入、素材和规则一致，比较分镜内容与执行开销。人工评价状态：UNRATED。

| 场景 | legacy 状态/时长 | planned 状态/时长 | 工具调用（legacy→planned） | 步骤（legacy→planned） |
| --- | --- | --- | --- | --- |
| 商品带货 | COMPLETED / 23 秒 | COMPLETED / 23 秒 | 3→3 | 6→9 |
| 商品展示 | COMPLETED / 26 秒 | COMPLETED / 26 秒 | 3→3 | 6→9 |
| 到店引流 | COMPLETED / 23 秒 | COMPLETED / 23 秒 | 3→3 | 6→9 |
| 活动推广 | COMPLETED / 23 秒 | COMPLETED / 24 秒 | 3→3 | 6→9 |

## 商品带货

[legacy 脚本](runs/raw_intent_story.output.md) · [planned 脚本](runs/creative_sales.output.md)

legacy 开场：等一下，这款你看清了吗？

planned 开场：等一下，这一步呢？

## 商品展示

[legacy 脚本](runs/raw_intent_demo.output.md) · [planned 脚本](runs/creative_demo.output.md)

legacy 开场：对准岩途随行杯，让商品关键位置进入画面。

planned 开场：先认准锁扣这一处。

## 到店引流

[legacy 脚本](runs/campaign_store.output.md) · [planned 脚本](runs/creative_store.output.md)

legacy 开场：先别走，要不要进去看看？

planned 开场：到柜台了，该出示哪一页？

## 活动推广

[legacy 脚本](runs/campaign_event.output.md) · [planned 脚本](runs/creative_event.output.md)

legacy 开场：你选好场次了吗？

planned 开场：想去是想去，你选好哪天了吗？

## 定向改写

[参考需求](inputs/raw_creative_reference.txt) · [成稿](runs/creative_reference.output.md) · [Trace](runs/creative_reference.trace.json)

检查引用、估时、事实和品牌通过后，创作诊断定位泛化开场、动机缺口和收尾未兑现，再定向重写。锁定相同内容时停止。

生成匿名评价表：`python examples/evaluate_creative.py --blind-output review.json --key-output review-key.json`。问卷与版本映射分别保存，评分字段初始为空。
