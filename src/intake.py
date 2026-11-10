"""Offline brief intake. Extraction is explicit and keeps the source of each field."""
import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass

from .intent import ACTIONS, ACTION_WORDS, GOALS, GOAL_WORDS, IntentExtractor, mock_intent
from .schema import CREATIVE_FIELDS, Brief, InputError, Material

FIELD_LABELS = {
    "topic": "主题", "audience": "受众", "platform": "平台", "target_seconds": "目标时长",
    "style": "风格", "format": "内容形式", "subject": "素材对应的主体",
    "search_hint": "检索词", "aspect_ratio": "画幅", "fictional": "虚构模式",
    "objective": "视频目标", "setting": "拍摄场景", "opening": "开场动作",
    "hook_line": "开场台词", "visible_result": "可见结果", "proof_id": "证据素材 ID", "cta": "收尾引导",
    "turn": "转折动作", "turn_line": "转折台词", "resolution": "人物结局",
    "creative_policy": "创意要求策略",
    "goal": "主目标", "campaign": "业务场景", "format_policy": "形式策略",
    "conversion_action": "转化动作", "conversion_destination": "承接入口",
}
ALIASES = {
    "主题": "topic", "选题": "topic", "受众": "audience", "目标人群": "audience",
    "平台": "platform", "投放平台": "platform", "时长": "target_seconds", "目标时长": "target_seconds",
    "风格": "style", "调性": "style", "形式": "format", "内容形式": "format",
    "主体": "subject", "产品": "subject", "素材主体": "subject", "检索词": "search_hint",
    "画幅": "aspect_ratio", "虚构": "fictional",
    "视频目标": "objective", "拍摄场景": "setting", "开场动作": "opening",
    "开场台词": "hook_line", "可见结果": "visible_result", "证据素材": "proof_id",
    "证据素材 ID": "proof_id", "收尾引导": "cta",
    "转折动作": "turn", "转折台词": "turn_line", "人物结局": "resolution",
    "创意要求策略": "creative_policy", "创意策略": "creative_policy",
    "主目标": "goal", "商业目标": "goal", "业务场景": "campaign", "形式策略": "format_policy",
    "转化动作": "conversion_action", "承接入口": "conversion_destination",
}
DEFAULTS = { "fictional": False, "aspect_ratio": "9:16", "search_hint": ""}
FORMATS = {
    "演示": "demo", "功能演示": "demo", "产品演示": "demo", "demo": "demo",
    "教程": "tutorial", "tutorial": "tutorial", "剧情": "story", "轻剧情": "story", "story": "story",
    "剧情带货": "sales_story", "sales_story": "sales_story", "商品展示": "demo",
    "实测对比": "comparison", "comparison": "comparison", "口播": "talking_head", "talking_head": "talking_head",
}
PLATFORMS = {"抖音": "抖音", "小红书": "小红书", "视频号": "视频号", "快手": "快手",
             "B站": "哔哩哔哩", "b站": "哔哩哔哩", "哔哩哔哩": "哔哩哔哩",
             "YouTube": "YouTube", "TikTok": "TikTok", "Instagram": "Instagram"}
SECTIONS = {"制作需求": "brief_text", "需求": "brief_text", "素材": "material_notes",
            "产品素材": "material_notes", "品牌规则": "brand_notes"}
NOTE = r"[^，,。；;！？!?\n]+"
DURATION = r"(?:\d+(?:\.\d+)?\s*(?:分钟|秒钟|秒|s|m)(?:\s*\d+\s*(?:秒钟|秒|s))?)"
NATURAL = {
    "topic": rf"(?:想拍|想做|请做)(?:一条|一个|一期)?(?:关于)?(?P<value>{NOTE})",
    "audience": rf"(?:给|面向|受众是|观众是)(?P<value>{NOTE})",
    "platform": r"(?:发到?|投放到?|发布在|上)\s*(?P<value>抖音|小红书|视频号|快手|B站|b站|哔哩哔哩|YouTube|TikTok|Instagram)",
    "target_seconds": rf"(?:时长\s*)?(?:控制在|不超过|最多|是|为)?\s*(?P<value>{DURATION})(?:以内|内)?",
    "style": rf"(?:风格(?:要|是|偏)?|调性(?:要|是|偏)?|语气(?:要|是|偏)?)(?P<value>{NOTE})",
    "subject": rf"(?:主体是|素材对应|产品是|用的是)(?P<value>{NOTE})",
    "setting": rf"(?:在|场景放在)(?P<value>{NOTE})拍摄",
    "aspect_ratio": r"(?:用|拍成)?(?P<value>竖屏|横屏|方形|9:16|16:9|1:1)",
}


@dataclass(frozen=True)
class Intake:
    fields: dict
    sources: dict
    missing: list[str]
    conflicts: dict
    questions: list[str]
    notes: list[dict]
    materials: tuple[Material, ...]
    material_sources: dict
    rules: tuple[dict, ...]
    invalid_fields: dict

    def report(self) -> dict:
        fields = self.fields
        paths = {"goal": "goal.primary", "audience": "goal.audience",
                 "objective": "goal.desired_response", "campaign": "context.campaign",
                 "format": "creative.format", "format_policy": "creative.format_policy",
                 "style": "creative.style", "conversion_action": "conversion.action",
                 "conversion_destination": "conversion.destination", "platform": "delivery.platform",
                 "target_seconds": "delivery.max_seconds", "aspect_ratio": "delivery.aspect_ratio",
                 "creative_policy": "creative.requirements_policy",
                 **{key: f"creative.user_requirements.{key}" for key in CREATIVE_FIELDS}}
        evidence = [{"field_path": paths.get(key, key), "value": record["selected"]["value"],
                     "origin": record["selected"]["kind"], "source": record["selected"]}
                    for key, record in self.sources.items()]
        format_constraint = {"field": "creative.format", "value": fields.get("format")}
        format_is_preferred = (fields.get("format_policy") == "propose"
                               and self.sources.get("format", {}).get("selected", {}).get("kind") == "brief_text")
        contract = {
            "goal": {"primary": fields.get("goal"), "audience": fields.get("audience"),
                     "desired_response": fields.get("objective")},
            "context": {"campaign": fields.get("campaign")},
            "creative": {"format": fields.get("format"), "format_policy": fields.get("format_policy"),
                         "style": fields.get("style"), "requirements_policy": fields.get("creative_policy", "locked"),
                         "user_requirements": {key: fields[key] for key in CREATIVE_FIELDS if fields.get(key)}},
            "conversion": {"action": fields.get("conversion_action"),
                           "destination": fields.get("conversion_destination")},
            "delivery": {"platform": fields.get("platform"), "max_seconds": fields.get("target_seconds"),
                         "aspect_ratio": fields.get("aspect_ratio")},
            "hard_constraints": [
                *([{"type": "max_seconds", "value": fields["target_seconds"]}]
                  if "target_seconds" in fields else []),
                *([format_constraint] if fields.get("format") and fields.get("format_policy") == "locked" else []),
                *[{"field": f"creative.user_requirements.{key}", "value": fields[key]} for key in CREATIVE_FIELDS
                  if fields.get(key) and fields.get("creative_policy", "locked") == "locked"],
                *self.rules,
            ],
            "soft_preferences": [
                *[{"field": f"creative.user_requirements.{key}", "value": fields[key]} for key in CREATIVE_FIELDS
                  if fields.get(key) and fields.get("creative_policy") == "reference"],
                *([{"field": "style", "value": fields["style"]}] if fields.get("style") else []),
                *([format_constraint] if format_is_preferred else []),
            ],
            "field_evidence": evidence,
            "issues": {"missing": self.missing, "conflicts": self.conflicts, "invalid": self.invalid_fields,
                       "questions": self.questions},
            "requires_human_review": bool(self.questions),
        }
        return {"status": "NEEDS_INPUT" if self.questions else "READY",
                "schema_version": "2.1", **asdict(self), "brief": contract}


def split_text(text: str) -> dict:
    parts = defaultdict(list)
    section = "brief_text"
    for line in text.splitlines():
        header = re.fullmatch(r"\s*(?:#{1,6}\s*)?(?:【([^】]+)】|\[([^\]]+)\]|([^：:]+)[：:]?)\s*", line)
        title = next((group for group in header.groups() if group), "").strip() if header else ""
        if title in SECTIONS:
            section = SECTIONS[title]
        else:
            parts[section].append(line)
    return {key: "\n".join(lines) for key, lines in parts.items()}


def _duration(value: str) -> int:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    value = re.sub(r"^(?:不超过|最多|控制在)\s*|\s*(?:以内|内)$", "", value)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(分钟|秒钟|秒|s|m)(?:\s*(\d+)\s*(?:秒钟|秒|s))?", value)
    if not match:
        raise ValueError("目标时长需要一个明确的上限，例如 30 秒")
    number, unit, seconds = match.groups()
    minute_unit = unit in {"分钟", "m"}
    if seconds is not None and not minute_unit:
        raise ValueError("请确认目标时长")
    # Decimal avoids rounding an inexact number to a valid second.
    whole, dot, fraction = number.partition(".")
    scale = 60 if minute_unit else 1
    numerator = int(whole + fraction) * scale
    denominator = 10 ** len(fraction) if dot else 1
    if numerator % denominator or numerator == 0:
        raise ValueError("目标时长需要为正整数秒")
    return numerator // denominator + int(seconds or "0")


def _value(key: str, value: object):
    if key == "target_seconds" and type(value) is int and value > 0:
        return value
    if key == "fictional" and type(value) is bool:
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("请填写明确值")
    value = value.strip().strip("「」“”")
    if key == "target_seconds":
        return _duration(value)
    if key == "goal":
        if value not in GOALS and value not in GOAL_WORDS:
            raise ValueError("请选择购买、线索、到店、报名、商品理解或品牌认知")
        return GOAL_WORDS.get(value, value)
    if key == "conversion_action":
        if value not in ACTIONS and value not in ACTION_WORDS:
            raise ValueError("请选择可识别的转化动作")
        return ACTION_WORDS.get(value, value)
    if key == "creative_policy":
        value = {"必须保留": "locked", "锁定": "locked", "仅供参考": "reference", "参考": "reference"}.get(value, value)
        if value not in {"locked", "reference"}:
            raise ValueError("请选择必须保留或仅供参考")
        return value
    if key == "format_policy":
        value = {"固定": "locked", "锁定": "locked", "由系统提案": "propose", "提案": "propose"}.get(value, value)
        if value not in {"locked", "propose"}:
            raise ValueError("请选择锁定或由系统提案")
        return value
    if key == "format":
        if value not in FORMATS:
            raise ValueError("请选择演示、教程、剧情或剧情带货")
        return FORMATS[value]
    if key == "fictional":
        if value not in {"是", "否", "true", "false"}:
            raise ValueError("请确认是否为原创虚构剧情")
        return value in {"是", "true"}
    if key == "aspect_ratio":
        value = {"竖屏": "9:16", "横屏": "16:9", "方形": "1:1"}.get(value, value.replace("：", ":"))
        if value not in {"9:16", "16:9", "1:1"}:
            raise ValueError("请确认画幅")
    if key == "platform":
        platforms = {canonical for alias, canonical in PLATFORMS.items() if alias in value}
        if len(platforms) > 1:
            raise ValueError("每次生成需明确一个发布平台")
        return PLATFORMS.get(value, value)
    return value


def _lines(text: str):
    for number, line in enumerate(text.splitlines(), 1):
        line = re.sub(r"^\s*(?:[-*]\s+|\d+[.、]\s*)?", "", line).strip()
        if line:
            yield number, line


def _facts(text: str) -> tuple[tuple[Material, ...], dict, list[str]]:
    materials, sources, questions = {}, {}, []
    invalid_ids = set()
    for number, line in _lines(text):
        match = re.fullmatch(r"\[([\w-]+)\]\s*(.+)", line)
        attrs = {}
        material_id = f"M{number:02d}"
        if match:
            material_id = match[1]
            for part in re.split(r"[|｜]", match[2]):
                field, separator, value = part.replace("：", ":", 1).partition(":")
                key, value = field.strip(), value.strip()
                if not separator or not value or key in attrs:
                    attrs = {}
                    break
                attrs[key] = value
        else:
            memo = re.fullmatch(
                r"(.+?)的《([^》]+)》(?:写着|注明|说明)[：:]?\s*[「“]([^」”]+)[」”]"
                r"[，,]\s*(?:可用画面是|画面是)[「“]([^」”]+)[」”][。.]?", line
            )
            if memo:
                attrs = dict(zip(("主体", "来源", "事实", "画面"), memo.groups(), strict=True))
        if not {"主体", "事实", "画面", "来源"} <= attrs.keys():
            questions.append(f"素材第 {number} 行请标明主体、事实原文、画面和来源。")
            continue
        material = Material(material_id, attrs["主体"], (),
                            tuple(tag.strip() for tag in attrs.get("标签", "").split("、") if tag.strip()),
                            attrs["事实"], attrs["画面"], attrs["来源"], attrs.get("操作", ""))
        ref = {"line": number, "text": line}
        if material.id in materials and materials[material.id] != material:
            questions.append(f"素材 ID {material.id} 对应不同内容，请确认后再使用。")
            invalid_ids.add(material.id)
        materials[material.id] = material
        sources.setdefault(material.id, []).append(ref)
    return tuple(material for key, material in materials.items() if key not in invalid_ids), sources, questions


def _rules(text: str | None, baseline_banned: tuple[str, ...]) -> tuple[tuple[dict, ...], list[str]]:
    if text is None or not text.strip():
        return (), ["请提供本次品牌规则，或明确写明「无额外品牌规则」。"]
    rules, questions = [], []
    lines = list(_lines(text))
    if len(lines) == 1 and lines[0][1] == "无额外品牌规则":
        return (), []
    for number, line in lines:
        match = re.fullmatch(r"(禁用词|必须出现的词)[：:]\s*(.+)", line)
        natural = re.fullmatch(r"(别写|不要说|必须说出)[「“]([^」”]+)[」”][。.]?", line)
        if natural and natural[2].strip():
            kind = "required" if natural[1] == "必须说出" else "banned"
            rules.append({"kind": kind, "term": natural[2].strip(), "line": number, "text": line})
            continue
        if not match:
            questions.append(f"品牌规则第 {number} 行「{line}」尚无法自动核验，请明确可检查的字词。")
            continue
        for term in re.split(r"[、，,]", match[2]):
            term = term.strip().strip("「」“”")
            if term:
                rules.append({"kind": "banned" if match[1] == "禁用词" else "required",
                              "term": term, "line": number, "text": line})
        if not any(rule["line"] == number for rule in rules):
            questions.append(f"品牌规则第 {number} 行缺少词语。")
    banned = {_rule_key(rule["term"]) for rule in rules if rule["kind"] == "banned"}
    banned.update(_rule_key(term) for term in baseline_banned)
    for rule in rules:
        if rule["kind"] == "required" and any(term in _rule_key(rule["term"]) for term in banned):
            questions.append(f"品牌规则冲突，「{rule['term']}」包含禁用词。")
    return tuple(rules), questions


def _rule_key(term: str) -> str:
    return "".join(term.casefold().split())


def normalize(raw: dict, baseline_banned: tuple[str, ...] = (),
              catalog: tuple[Material, ...] = (),
              extract_intent: IntentExtractor = mock_intent, source_file: str = "") -> Intake:
    text = raw.get("brief_text", "")
    confirmed = raw.get("confirmed", {})
    material_notes = raw.get("material_notes", "")
    brand_notes = raw.get("brand_notes")
    if (not isinstance(text, str) or not isinstance(material_notes, str)
            or (brand_notes is not None and not isinstance(brand_notes, str))
            or not isinstance(confirmed, dict) or confirmed.keys() - FIELD_LABELS.keys()):
        raise InputError("原始需求、素材与规则需为文本，confirmed 仅接收支持的标准字段。")

    candidates = defaultdict(list)
    notes, issues = [], defaultdict(list)
    semantic_context = []

    def add(key: str, value: object, source: dict):
        try:
            parsed = _value(key, value)
        except ValueError as exc:
            issues[key].append({"source": source, "detail": str(exc),
                                "code": "EMPTY" if isinstance(value, str) and not value.strip() else "INVALID_OR_AMBIGUOUS"})
        else:
            candidates[key].append({"value": parsed, **source})

    labels = "|".join(sorted(ALIASES, key=len, reverse=True))
    labeled = re.compile(rf"^({labels})[：:]\s*(.*)$")
    action_fields = {"setting", "opening", "turn", "resolution", "hook_line", "turn_line"}
    for number, line in _lines(text):
        head = labeled.fullmatch(line)
        separator = (rf"[。；;，,](?=\s*(?:{labels})[：:])"
                     if head and ALIASES[head[1]] in action_fields
                     else rf"[；;。]|[，,](?=\s*(?:{labels})[：:])")
        for clause in re.split(separator, line):
            clause = clause.strip()
            if not clause:
                continue
            ref = {"kind": "brief_text", "line": number, "text": clause, "source_file": source_file, "section": "brief_text"}
            field = labeled.fullmatch(clause)
            if field:
                key = ALIASES[field[1]]
                if key == "format" and field[2] in {"带货", "商品带货"}:
                    add("goal", "purchase", ref)
                else:
                    add(key, field[2], ref)
                continue
            requested_format = re.fullmatch(r"(必须|最好|优先)拍成(剧情|功能演示|教程|口播)", clause)
            if requested_format:
                add("format", requested_format[2], ref)
                add("format_policy", "locked" if requested_format[1] == "必须" else "propose", ref)
                continue
            semantic_context.append(ref)
            objective = re.fullmatch(r"(?:希望观众|看完希望观众)(.+)", clause)
            if objective:
                add("objective", objective[1], ref)
                continue
            for sentence_part in re.split(r"[，,]", clause):
                part = sentence_part.strip()
                for key, pattern in NATURAL.items():
                    match = re.fullmatch(pattern, part)
                    if match:
                        add(key, match["value"].strip(), {**ref, "text": part})
                        break
                else:
                    if re.match(r"^(?:时长|控制在|不超过|最多)", part):
                        issues["target_seconds"].append(
                            {"source": {**ref, "text": part}, "detail": "请给出一个明确的时长上限"})
                    elif part:
                        notes.append({**ref, "text": part})

    text_for_intent = "\n".join(ref["text"] for ref in semantic_context)
    if text_for_intent:
        for key, value, quote in extract_intent(text_for_intent):
            if key not in {"goal", "format", "conversion_action", "conversion_destination", "style"} or not quote:
                continue
            for ref in semantic_context:
                if quote in ref["text"]:
                    add(key, value, {**ref, "kind": "semantic_candidate", "text": quote})

    for key, value in confirmed.items():
        add(key, value, {"kind": "confirmed", "field": key, "text": value})

    fields, sources, conflicts, questions = {}, {}, {}, []
    for key in FIELD_LABELS:
        options = candidates[key]
        resolved = next((option for option in options if option["kind"] == "confirmed"), None)
        if resolved:
            fields[key] = resolved["value"]
            sources[key] = {"selected": resolved, "candidates": options, "issues": issues[key]}
        elif len({option["value"] for option in options}) > 1:
            conflicts[key] = options
            values = "、".join(str(value) for value in dict.fromkeys(option["value"] for option in options))
            questions.append(f"{FIELD_LABELS[key]}出现不同值（{values}），请确认使用哪一个。")
        elif issues[key]:
            questions.extend(f"{FIELD_LABELS[key]}需确认（{issue['detail']}）。" for issue in issues[key])
        elif options:
            fields[key] = options[0]["value"]
            sources[key] = {"selected": options[0], "candidates": options}
        elif key in DEFAULTS:
            fields[key] = DEFAULTS[key]
            sources[key] = {"selected": {"kind": "default", "value": DEFAULTS[key]}}
    if not fields.get("goal") and "goal" not in conflicts and not issues["goal"]:
        topic = fields.get("topic", "")
        if "带货" in topic and not re.search(r"不做|不要|不是|不需要", topic):
            fields["goal"] = "purchase"
            sources["goal"] = {"selected": {**sources["topic"]["selected"],
                                           "kind": "inferred", "value": "purchase", "from": "topic"}}
        elif fields.get("conversion_action") in {"open_product_card", "purchase"}:
            fields["goal"] = "purchase"
            sources["goal"] = {"selected": {**sources["conversion_action"]["selected"],
                                           "kind": "inferred", "value": "purchase",
                                           "from": "conversion_action"}}
        elif any("剧情引流" in ref["text"] for ref in semantic_context):
            questions.append("剧情形式已识别，请确认引流到店、私信还是预约入口。")
    if not fields.get("format_policy") and "format_policy" not in conflicts and not issues["format_policy"]:
        origin = sources.get("format", {}).get("selected", {}).get("kind")
        policy = "locked" if origin in {"brief_text", "confirmed"} else "propose"
        fields["format_policy"] = policy
        sources["format_policy"] = {"selected": {"kind": "inferred", "value": policy, "from": "format"}}

    brief, missing = None, []
    try:
        brief, missing = Brief.parse(fields)
    except InputError as exc:
        questions.append(str(exc))
    if brief and "format" not in fields:
        fields["format"] = brief.format
        sources["format"] = {"selected": {"kind": "proposal", "value": brief.format, "from": "brief"}}
    blocked_fields = {FIELD_LABELS[key] for key in FIELD_LABELS if key in conflicts or issues[key]}
    missing = [label for label in missing if label not in blocked_fields]
    questions.extend(f"请补充{label}。" for label in missing)
    questions.extend(f"需求第 {note['line']} 行「{note['text']}」含未归类的强制要求，请转成字段或品牌规则。"
                     for note in notes if re.search(r"必须|禁止|不得|不能|不许|务必", note["text"]))
    materials, material_sources, material_questions = _facts(material_notes)
    if catalog:
        pool = {material.id: material for material in materials}
        for material in catalog:
            if material.id in material_sources and pool.get(material.id) != material:
                material_questions.append(f"素材 ID {material.id} 在笔记和附件中不一致，请确认。")
                pool.pop(material.id, None)
            else:
                pool[material.id] = material
            material_sources.setdefault(material.id, []).append(
                {"kind": "catalog", "source": material.source, "id": material.id})
        materials = tuple(pool.values())
    if brief and not brief.fictional and not materials and not material_questions:
        material_questions.append("请提供带事实原文和出处的素材。")
    rules, rule_questions = _rules(brand_notes, baseline_banned)
    return Intake(fields, sources, missing, conflicts, list(dict.fromkeys(
        questions + material_questions + rule_questions)), notes, materials, material_sources, rules,
        {key: problems for key, problems in issues.items()
         if problems and sources.get(key, {}).get("selected", {}).get("kind") != "confirmed"})
