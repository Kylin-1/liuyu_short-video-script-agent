"""Business goal, conversion and creative choices are independent."""
import re
from typing import Protocol

GOALS = {
    "purchase": "促进购买", "store_visit": "到店引流", "lead": "获取线索",
    "event_signup": "活动报名", "product_understanding": "促进商品理解", "brand_awareness": "品牌认知",
}
ACTIONS = {
    "open_product_card": "点商品卡", "purchase": "下单", "claim_coupon": "领券",
    "visit_store": "到店", "contact": "私信咨询", "submit_form": "提交表单", "reserve": "预约",
}
GOAL_ACTIONS = {
    "purchase": {"open_product_card", "purchase"},
    "store_visit": {"claim_coupon", "visit_store"},
    "lead": {"contact", "submit_form", "claim_coupon"},
    "event_signup": {"reserve", "submit_form"},
}
GOAL_WORDS = {**{name: code for code, name in GOALS.items()},
              "带货": "purchase", "促进下单": "purchase", "预约报名": "event_signup"}
ACTION_WORDS = {**{name: code for code, name in ACTIONS.items()},
                "点击商品卡": "open_product_card", "到店核销": "visit_store",
                "打开商品卡": "open_product_card", "领取优惠券": "claim_coupon"}
INPUT_FIELDS = ("goal", "campaign", "format_policy", "conversion_action", "conversion_destination")
CTA_PATTERNS = {
    "open_product_card": "点开{destination}，看商品详情",
    "purchase": "在{destination}下单",
    "claim_coupon": "到{destination}领券",
    "visit_store": "到{destination}看看",
    "contact": "通过{destination}私信咨询",
    "submit_form": "在{destination}填写并提交表单",
    "reserve": "到{destination}预约",
}


class IntentExtractor(Protocol):
    """Each result contains a field, a candidate value and its supporting raw text."""

    def __call__(self, text: str) -> list[tuple[str, str, str]]: ...


def mock_intent(text: str) -> list[tuple[str, str, str]]:
    """Offline, precision-first semantic candidates; never supplies an offer or destination."""
    rules = (
        ("goal", "purchase", ("带货", "促进下单")),
        ("goal", "store_visit", ("引流到店", "到店引流")),
        ("goal", "event_signup", ("预约报名", "活动报名")),
        ("goal", "lead", ("获取线索", "收集线索")),
        ("goal", "brand_awareness", ("品牌认知", "品牌曝光")),
        ("goal", "product_understanding", ("看懂商品功能", "促进商品理解")),
        ("format", "story", ("小剧情", "剧情短片", "剧情引流", "拍成剧情")),
        ("format", "demo", ("功能演示", "商品展示")),
        ("format", "tutorial", ("领券教程", "操作教程")),
        ("format", "comparison", ("实测对比",)),
        ("format", "talking_head", ("口播形式",)),
        ("conversion_action", "open_product_card", ("挂商品卡", "点商品卡")),
    )
    candidates = []
    for line in text.splitlines():
        if re.search(r"不是|不要|不做|不需要|不用于", line):
            continue
        candidates.extend((field, value, line) for field, value, phrases in rules
                          if any(phrase in line for phrase in phrases))
        demonstration = re.search(r"展示[^，。；]{1,20}(?:怎么|如何)(?:用|锁|打开|操作)", line)
        if demonstration:
            candidates.append(("format", "demo", demonstration[0]))
        if "挂商品卡" in line or "点商品卡" in line:
            candidates.append(("conversion_destination", "商品卡", line))
        target = re.search(r"(门店小程序|活动页)\s*(领券|预约|报名)", line)
        if target:
            destination, action = target.groups()
            candidates.append(("conversion_destination", destination, target[0]))
            candidates.append(("conversion_action", "claim_coupon" if action == "领券" else "reserve", target[0]))
            if destination == "门店小程序" and action == "领券":
                candidates.append(("goal", "store_visit", target[0]))
            elif action in {"预约", "报名"}:
                candidates.append(("goal", "event_signup", target[0]))
    return candidates
