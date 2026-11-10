"""Offline creative adapters. Heuristics validate the loop, not audience appeal."""
from dataclasses import asdict, replace
import re

from .schema import Beat, Brief, CREATIVE_FIELDS, CreativePlan, Draft, Material
from .tools import normalized, read_units


def primary_material(brief: Brief, materials: tuple[Material, ...]) -> Material | None:
    return next((item for item in materials
                 if (not brief.proof_id or item.id == brief.proof_id)
                 and normalized(brief.visible_result) in normalized(item.visual)), None)


def evidence_pack(materials: tuple[Material, ...]) -> dict:
    return {"facts": [asdict(item) for item in materials],
            "boundaries": ["仅允许引用这些事实原文，不从画面或剧情推导性能。",
                           "缺少效果数据时，不得添加效率、销量或转化提升结论。",
                           "虚构人物和对白不构成产品测试证据。"]}


def propose(brief: Brief, materials: tuple[Material, ...]) -> tuple[CreativePlan, ...]:
    source = primary_material(brief, materials)
    fact = source.fact if source else ""
    # Negative capability records must not trigger a positive demonstration seed.
    seed_fact = "" if re.search(r"不支持|不带|不含|不提供|没有|无|未|禁止", fact) else fact
    # These four offline seeds demonstrate different causal structures. They are not an LLM.
    if "锁扣" in seed_fact:
        focus, goal = "锁扣", "确认锁扣的位置后出门"
        setting = "玄关，包放在门边"
        if any(word in brief.audience for word in ("旅行", "户外", "露营")):
            setting = "出发前的行李整理台，背包放在旁边"
        opening, hook = "同伴拿起包要走，主角伸手按住包带，另一只手指向杯盖。", "等一下，这一步呢？"
        turn, line = "同伴停住，把杯盖朝向主角；主角的手指停在锁扣旁。", "锁扣的位置，先看清。"
        obstacle = "同伴准备离开，主角还没有看清锁扣的位置"
        resolution = "主角收回指着杯盖的手，接过包，与同伴一起走出门。"
    elif "字幕" in seed_fact:
        focus, goal = "字幕", "看清视频里说的话"
        setting = "桌前，两人看着同一块屏幕"
        opening, hook = "朋友指着屏幕上一闪而过的台词，主角把进度条停住。", "刚才那句，你看清了吗？"
        turn, line = "朋友把手移到屏幕边缘，两人的视线跟向可用素材里的字幕。", "先别重播，看这里。"
        obstacle = "人物错过台词，需要把注意力转到字幕"
        resolution = "朋友点点头，主角松开进度条，两人继续往下看。"
    elif "券码" in seed_fact:
        focus, goal = "券码", "在柜台出示正确的页面"
        setting = "门店柜台前，手机屏幕朝向自己"
        opening, hook = "主角把手机伸向朋友，朋友看了一眼，没有接过去。", "到柜台了，该出示哪一页？"
        turn, line = "朋友指向手机，主角先收回手，把页面看清。", "券码这一页，别拿错。"
        obstacle = "人物不确定应出示哪个页面"
        resolution = "主角把手机朝向店员，停在柜台前等待确认。"
    elif any(word in seed_fact for word in ("预约", "报名")):
        focus, goal = "预约", "确认想参加的日期后查看预约入口"
        setting = "两位朋友站在活动海报旁"
        opening, hook = "朋友拿着包催主角走，主角把手里的活动海报转给他看。", "想去是想去，你选好哪天了吗？"
        turn, line = "朋友停住，在手机上翻出活动页面，两人对照海报。", "先看预约页，再决定。"
        obstacle = "人物想参加活动，但尚未确认日期"
        resolution = "两人指向选中的日期，主角记下时间，再拿起手机。"
    else:
        focus, goal = "细节", "看清这一处再决定下一步"
        setting = "桌面前，主体位于画面中央"
        opening, hook = f"主角伸手准备收起{brief.subject or '桌上的便签'}，同伴抬手示意等一下。", "先等一下，你刚才看的是哪一处？"
        turn, line = "同伴把手移开，主角俯身，视线跟到画面中央。", "这处细节，再看一眼。"
        obstacle = "人物准备结束观看，关键细节还没有看清"
        resolution = "主角回到原来的位置，指一指刚才看的地方，再做出继续了解的动作。"
    if brief.fictional:
        focus, goal, obstacle = "便签", "把想说的话交给对方", "人物到了门口仍在犹豫"
        opening, hook = "主角站在门口，手握便签，抬起的手又放下。", "这句话，要不要当面说？"
        turn, line = "门内的人转过身，主角没有再把便签藏回身后。", "算了，就现在。"
        resolution = "对方接过便签，主角放下绷着的肩膀，两人一起进门。"
        setting = "聚会门口，室内有谈话声"
    if brief.goal == "store_visit" and "锁扣" in seed_fact:
        setting = "门店体验台前，两人停在样品旁"
        goal, obstacle = "在进店了解之前看清锁扣细节", "朋友准备离开，主角还没看清样品"
        opening, hook = "朋友已经转身，主角叫住他，手指落在样品杯盖旁。", "先别走，这一步你看清了吗？"
        resolution = "两人留在体验台前，主角拿出手机查看指定入口。"
    result = []
    for index in range(2):
        choices = dict(setting=setting, opening=opening, hook_line=hook,
                       turn=turn, turn_line=line, resolution=resolution)
        if index:
            choices.update(opening=f"近景先给出主角停在{focus}旁的手，同伴从画外伸手示意。",
                           hook_line=f"先别动，{focus}看清了吗？",
                           turn="主角停住动作，顺着同伴的手势看向镜头中央。",
                           turn_line=f"先看{focus}，再往下。")
        origins = []
        for name in CREATIVE_FIELDS:
            locked = brief.creative_policy == "locked" and bool(getattr(brief, name))
            if locked:
                choices[name] = getattr(brief, name)
            origins.append((name, "user_locked" if locked else "mock_proposal"))
        if brief.format not in {"story", "sales_story"}:
            choices["opening"] = (brief.opening if brief.creative_policy == "locked" and brief.opening else
                                  f"镜头对准{brief.subject}，从素材里的关键位置开始，手指沿画面边缘指示。")
            choices["hook_line"] = (brief.hook_line if brief.creative_policy == "locked" and brief.hook_line else
                                    f"{focus}在哪里？跟着这个画面看。" if not index else f"先认准{focus}这一处。")
        presentation = f"按 {brief.aspect_ratio} 构图，为{brief.platform}制作；平台差异待实投验证。"
        if "快节奏" in brief.style:
            presentation += "用短句，在动作完成处切镜。"
        elif any(word in brief.style for word in ("克制", "安静")):
            presentation += "减少催促式语气，保留现场声。"
        else:
            presentation += f"采用「{brief.style or '自然'}」表达，避免夸大商品能力。"
        result.append(CreativePlan(
            f"C{index+1:02d}", (("人物阻碍" if not index else "细节悬念")
                                 if brief.format in {"story", "sales_story"} else ("问题引导" if not index else "细节观察")),
            f"面向{brief.audience}，假设他们会关心「{goal}」；该洞察尚未经观众验证。",
            brief.objective or goal, (brief.turn if brief.creative_policy == "locked" and brief.turn else obstacle), f"仅通过素材 {source.id} 呈现「{fact}」" if source else "纯虚构人物行动，不包含商品事实",
            choices["resolution"], brief.resolved_cta or "先完成观察或人物行动，不添加未授权转化入口", presentation,
            focus, **choices, material_ids=(source.id,) if source else (),
            assumptions=("人物、动机、场景和对白为创作设定，不代表真实用户见证。",),
            field_origins=tuple(origins)))
    unique = {}
    for plan in result:
        unique.setdefault(tuple(getattr(plan, key) for key in CREATIVE_FIELDS), plan)
    return tuple(unique.values())


def select(brief: Brief, plans: tuple[CreativePlan, ...]) -> tuple[str, str]:
    if brief.target_seconds <= 20 or brief.format not in {"story", "sales_story"}:
        plan = min(plans, key=lambda item: read_units(item.hook_line + item.turn_line))
        return plan.id, "选择较短的开场方案，为事实镜头和收尾保留预算；最终以估时工具为准。"
    return plans[0].id, "采用人物阻碍方案，先建立行动目标，再由有依据的细节承接剧情。"


def effective_brief(brief: Brief, plan: CreativePlan) -> Brief:
    return replace(brief, **{key: getattr(plan, key) for key in CREATIVE_FIELDS},
                   objective=brief.objective or plan.protagonist_goal)


def write(brief: Brief, plan: CreativePlan, materials: tuple[Material, ...]) -> Draft:
    values = {key: getattr(plan, key) for key in CREATIVE_FIELDS}
    # A supplied reference is a first-draft input, not a guarantee of creative quality.
    if brief.creative_policy == "reference":
        values.update({key: getattr(brief, key) for key in CREATIVE_FIELDS if getattr(brief, key)})
    source = next((item for item in materials if item.id in plan.material_ids), None)
    beats = []
    def add(purpose, action, voiceover="", subtitle="", material_id=""):
        beats.append(Beat(f"S{len(beats)+1:02d}", purpose, action, voiceover, subtitle, material_id))
    add("hook", f"{values['setting'].rstrip('。')}。{values['opening']}", values['hook_line'])
    story = brief.format in {"story", "sales_story"}
    if story:
        add("turn", values['turn'], values['turn_line'])
    if source:
        if source.operation and brief.format != "talking_head":
            add("operation", source.operation, material_id=source.id)
        add("payoff", source.visual, source.fact.rstrip("。") + "。", material_id=source.id)
    else:
        add("payoff", brief.visible_result or "主角把便签递过去，对方伸手接住。")
    if story:
        add("resolution", values['resolution'], subtitle=brief.resolved_cta)
    else:
        add("cta", "回到开场构图，手再次指向刚才看的位置。",
            voiceover="这一次，看清了吗？", subtitle=brief.resolved_cta)
    return Draft(brief.topic, tuple(beats))


GENERIC = ("这个功能怎么用", "先看这里", "接下来会发生什么", "大家好", "欢迎来到", "给你介绍一款")


def critique(brief: Brief, plan: CreativePlan, draft: Draft, scenes) -> dict:
    issues = []
    def add(beat, field, code, goal):
        issues.append({"scene_id": beat.id, "field": field, "code": code,
                       "evidence": getattr(beat, field), "revision_goal": goal,
                       "preserve": ["素材原文与引用", "优惠条件", "指定转化入口", "非目标镜头"]})
    beats = [scene.beat for scene in scenes]
    first = beats[0]
    if not first.voiceover.strip() or any(term in first.voiceover for term in GENERIC):
        add(first, "voiceover", "GENERIC_HOOK", f"让开场围绕「{plan.focus}」提出具体期待，删除泛泛介绍。")
    story = brief.format in {"story", "sales_story"}
    if story:
        turn = next((beat for beat in beats if beat.purpose == "turn"), None)
        if turn and any(term in turn.action for term in ("然后展示产品", "展示商品", "开始介绍产品")):
            add(turn, "action", "MISSING_MOTIVATION", "交代人物为何停下或改变动作，再承接已有素材。")
        close = next((beat for beat in beats if beat.purpose == "resolution"), None)
        if close and any(term in close.action for term in ("展示商品", "结束视频", "摆拍产品")):
            add(close, "action", "UNRESOLVED_PAYOFF", "用人物行动回应开场目标，保留指定转化入口。")
    previous = set()
    for beat in beats:
        key = normalized(beat.voiceover)
        if key and key in previous and not beat.material_id:
            add(beat, "voiceover", "REDUNDANT_COPY", "删除重复解释，改成承接当前动作的短句。")
        if key:
            previous.add(key)
    return {"passed": not issues, "issues": issues,
            "scope": "Mock 创作诊断，仅识别泛化开场、显式动机缺口、未兑现收尾和重复口播。",
            "human_review_required": True,
            "human_review_items": ["开场是否值得继续看", "人物动机是否自然", "商品介入是否生硬", "结尾是否兑现", "实际可拍性"]}


def rewrite(brief: Brief, plan: CreativePlan, draft: Draft, issues: list[dict]) -> Draft:
    fixes = {(issue['scene_id'], issue['field']): issue['code'] for issue in issues}
    beats = []
    for beat in draft.beats:
        changes = {}
        for name in ("action", "voiceover", "subtitle"):
            code = fixes.get((beat.id, name))
            if code == "GENERIC_HOOK":
                changes[name] = plan.hook_line
            elif code == "MISSING_MOTIVATION":
                changes[name] = plan.turn
            elif code == "UNRESOLVED_PAYOFF":
                changes[name] = plan.resolution
            elif code == "REDUNDANT_COPY":
                changes[name] = ""
        beats.append(replace(beat, **changes))
    return replace(draft, beats=tuple(beats))


def creative_lock(brief: Brief, beat: Beat, field: str) -> bool:
    if beat.material_id or (field == "subtitle" and beat.subtitle == brief.resolved_cta and brief.resolved_cta):
        return True
    mapping = {("hook", "action"): ("opening", "setting"), ("hook", "voiceover"): ("hook_line",),
               ("turn", "action"): ("turn",), ("turn", "voiceover"): ("turn_line",),
               ("resolution", "action"): ("resolution",)}
    return brief.creative_policy == "locked" and any(getattr(brief, key)
               for key in mapping.get((beat.purpose, field), ()))
