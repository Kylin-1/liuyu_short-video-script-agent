"""Shared contracts for the producer, specialists and local tools."""
from dataclasses import dataclass, field
from typing import Any, Literal

from .intent import ACTIONS, CTA_PATTERNS, GOALS, GOAL_ACTIONS, INPUT_FIELDS


class ModelError(RuntimeError):
    pass


class InputError(ValueError):
    pass


CREATIVE_FIELDS = ("setting", "opening", "hook_line", "turn", "turn_line", "resolution")


@dataclass(frozen=True)
class Brief:
    topic: str
    audience: str
    platform: str
    target_seconds: int
    style: str
    format: Literal["demo", "tutorial", "story", "sales_story", "comparison", "talking_head"]
    fictional: bool
    subject: str
    search_hint: str
    aspect_ratio: str
    objective: str = ""
    setting: str = ""
    opening: str = ""
    hook_line: str = ""
    visible_result: str = ""
    proof_id: str = ""
    cta: str = ""
    turn: str = ""
    turn_line: str = ""
    resolution: str = ""
    goal: str = ""
    campaign: str = ""
    format_policy: str = ""
    conversion_action: str = ""
    conversion_destination: str = ""
    creative_policy: str = "locked"

    @property
    def conversion_story(self) -> bool:
        return self.format == "sales_story" or (
            self.format == "story" and bool(self.goal) and not self.fictional
        )

    @property
    def resolved_cta(self) -> str:
        if self.cta:
            return self.cta
        if self.conversion_action and self.conversion_destination:
            return CTA_PATTERNS[self.conversion_action].format(destination=self.conversion_destination)
        return ""

    @property
    def production(self) -> bool:
        return (self.conversion_story or self.format == "talking_head"
                or any((self.goal, self.conversion_action, self.objective, self.setting,
                        self.opening, self.hook_line, self.visible_result, self.proof_id, self.cta)))

    @classmethod
    def parse(cls, raw: object) -> tuple["Brief | None", list[str]]:
        if not isinstance(raw, dict):
            raise InputError("需求必须是 JSON 对象。")

        def string(key: str, default: str = "") -> str:
            value = raw.get(key, default)
            if not isinstance(value, str):
                raise InputError(f"{key} 必须是字符串。")
            return value.strip()

        required = {"topic": "主题", "audience": "受众", "platform": "平台", "style": "风格"}
        values = {key: string(key) for key in required}
        missing = [label for key, label in required.items() if not values[key]]
        seconds = raw.get("target_seconds")
        if seconds is None:
            missing.append("目标时长")
        elif type(seconds) is not int or seconds <= 0:
            raise InputError("目标时长必须为正整数秒。")
        business = {key: string(key) for key in INPUT_FIELDS}
        if business["goal"] and business["goal"] not in GOALS:
            raise InputError("商业目标不在支持范围内。")
        if business["conversion_action"] and business["conversion_action"] not in ACTIONS:
            raise InputError("转化动作不在支持范围内。")
        policy = business["format_policy"]
        if policy not in {"", "locked", "propose"}:
            raise InputError("形式策略应为 locked 或 propose。")
        goal, action = business["goal"], business["conversion_action"]
        if action and not goal:
            missing.append("主目标")
        if goal in GOAL_ACTIONS and not action:
            missing.append("转化动作")
        elif goal in GOAL_ACTIONS and action not in GOAL_ACTIONS[goal]:
            raise InputError("转化动作与主目标不匹配，请确认要达成的主要结果。")
        if (action or goal in GOAL_ACTIONS) and not business["conversion_destination"]:
            missing.append("承接入口")
        if business["conversion_destination"] and not action and goal not in GOAL_ACTIONS:
            missing.append("转化动作")

        fictional = raw.get("fictional", False)
        if type(fictional) is not bool:
            raise InputError("虚构标记必须为布尔值。")
        suggested = "story" if fictional or raw.get("turn") or raw.get("resolution") else (
            "tutorial" if action in {"claim_coupon", "reserve", "submit_form"} else "demo"
        )
        format_name = string("format", "")
        if not format_name:
            if policy == "locked":
                missing.append("内容形式")
            format_name = suggested
        if format_name not in {"demo", "tutorial", "story", "sales_story", "comparison", "talking_head"}:
            raise InputError("请选择支持的内容形式。")
        if format_name == "comparison":
            raise InputError("实测对比已能识别。当前生成器需要另行接入对照素材与对比校验。")
        if fictional and format_name != "story":
            raise InputError("仅 story 可以显式设为虚构。")
        subject = string("subject")
        if not fictional and not subject:
            missing.append("素材对应的主体")
        if fictional and subject:
            raise InputError("虚构模式仅适用于无事实主体的原创剧情。")
        aspect_ratio = string("aspect_ratio", "9:16")
        if aspect_ratio not in {"9:16", "16:9", "1:1"}:
            raise InputError("画幅可选 9:16、16:9 或 1:1。")
        hint = string("search_hint")
        creative = {key: string(key) for key in
                    ("objective", "setting", "opening", "hook_line", "visible_result", "proof_id", "cta",
                     "turn", "turn_line", "resolution")}
        if action and business["conversion_destination"] and creative["cta"]:
            expected_cta = CTA_PATTERNS[action].format(destination=business["conversion_destination"])
            if creative["cta"].rstrip("。") != expected_cta:
                raise InputError("转化引导文案与结构化动作或入口可能不一致，请保留结构化字段或确认统一文案。")
        creative_policy = string("creative_policy", "locked")
        if creative_policy not in {"locked", "reference"}:
            raise InputError("创意要求策略应为 locked 或 reference。")
        if fictional and creative["proof_id"]:
            raise InputError("纯虚构模式的证据素材 ID 应留空。")
        if missing:
            return None, missing
        return cls(**values, target_seconds=seconds, format=format_name, fictional=fictional,
                   subject=subject, search_hint=hint, aspect_ratio=aspect_ratio, creative_policy=creative_policy, **creative, **business), []


@dataclass(frozen=True)
class Material:
    id: str
    subject: str
    aliases: tuple[str, ...]
    tags: tuple[str, ...]
    fact: str
    visual: str
    source: str = ""
    operation: str = ""


@dataclass(frozen=True)
class Beat:
    id: str
    purpose: str
    action: str
    voiceover: str = ""
    subtitle: str = ""
    material_id: str = ""


@dataclass(frozen=True)
class Draft:
    title: str
    beats: tuple[Beat, ...]


@dataclass(frozen=True)
class Scene:
    beat: Beat
    planned_seconds: int
    minimum_visual_seconds: int
    continuity: str = ""
    framing: str = ""
    sound: str = ""
    transition: str = ""


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    args: dict[str, Any] = field(default_factory=dict)
    decision_source: str = "mock"


@dataclass(frozen=True)
class CreativePlan:
    id: str
    approach: str
    audience_insight: str
    protagonist_goal: str
    obstacle: str
    product_role: str
    payoff: str
    cta_reason: str
    presentation: str
    focus: str
    setting: str
    opening: str
    hook_line: str
    turn: str
    turn_line: str
    resolution: str
    material_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    field_origins: tuple[tuple[str, str], ...]


@dataclass
class State:
    brief: Brief | None
    missing: list[str]
    materials: tuple[Material, ...] = ()
    searched: bool = False
    searches: int = 0
    revisions: int = 0
    duration_revisions: int = 0
    tool_calls: int = 0
    creative_mode: str = "planned"
    plans: tuple[CreativePlan, ...] = ()
    plan: CreativePlan | None = None
    selection_reason: str = ""
    creative_review: dict | None = None
    creative_revisions: int = 0
    draft: Draft | None = None
    scenes: tuple[Scene, ...] = ()
    version: int = 0
    quality: dict | None = None
    review: dict | None = None
    last: dict = field(default_factory=dict)

    def invalidate_checks(self) -> None:
        self.quality = None
        self.review = None
        self.creative_review = None
