"""Replaceable model boundary and deterministic offline implementations."""
from dataclasses import replace
import re
from typing import Protocol

from .intent import GOAL_ACTIONS
from .claims import unsupported_clauses
from . import creative
from .schema import Beat, Brief, CreativePlan, Decision, Draft, Material, Scene, State
from .tools import normalized, text_seconds


def disclosure_sources(issues: list[dict], materials: tuple[Material, ...]) -> tuple[Material, ...]:
    """Brand instructions alone cannot substantiate a factual disclosure."""
    selected = {}
    for issue in issues:
        term = issue.get("value", "")
        source = next((item for item in materials if isinstance(term, str) and term.strip()
                       and normalized(term) in normalized(item.fact)
                       and not unsupported_clauses(term, (item.fact,))), None)
        if source is None:
            return ()
        selected[source.id] = source
    return tuple(selected.values())


class StudioModels(Protocol):
    mode: str

    def producer(self, state: State) -> Decision: ...
    def propose_concepts(self, brief: Brief, materials: tuple[Material, ...]) -> tuple[CreativePlan, ...]: ...
    def select_concept(self, brief: Brief, plans: tuple[CreativePlan, ...]) -> tuple[str, str]: ...
    def write_concept(self, brief: Brief, plan: CreativePlan, materials: tuple[Material, ...]) -> Draft: ...
    def critique(self, brief: Brief, plan: CreativePlan, draft: Draft, scenes: tuple[Scene, ...]) -> dict: ...
    def rewrite_creative(self, brief: Brief, plan: CreativePlan, draft: Draft, issues: list[dict]) -> Draft: ...
    def props(self, brief: Brief, query: str) -> tuple[str, str]: ...
    def screenwriter(self, brief: Brief, materials: tuple[Material, ...]) -> Draft: ...
    def revise_copy(self, draft: Draft, scene_ids: tuple[str, ...]) -> Draft: ...
    def director(self, brief: Brief, draft: Draft, compact: bool) -> tuple[Scene, ...]: ...
    def reviewer(self, brief: Brief, draft: Draft, scenes: tuple[Scene, ...],
                 materials: tuple[Material, ...]) -> dict: ...


class MockModels:
    mode = "mock"
    creative_model_mode = "mock"

    def producer(self, state: State) -> Decision:
        last = state.last
        if last.get("status") == "tool_error":
            if last["args"].get("retry"):
                return Decision("STOP", "工具重试后仍不可用。", {"status": "TOOL_FAILED"})
            return Decision(last["action"], "工具返回异常，尝试一次有限重试。",
                            {**last["args"], "retry": True})
        if state.missing:
            return Decision("ASK", "需要补齐关键创作需求。", {"fields": state.missing})
        if not state.searched:
            return Decision("FIND_MATERIAL", "请道具准备可用素材。", {"query": state.brief.search_hint})
        if not state.brief.fictional and not state.materials:
            if last["args"].get("query") and state.searches == 1:
                return Decision("FIND_MATERIAL", "关键词无匹配，保留同一主体并放宽关键词。",
                                {"query": ""})
            proof_id = state.brief.proof_id
            field = f"属于该主体的素材 {proof_id}" if proof_id else "可核实的素材"
            return Decision("ASK", "未查到可支持该主体的素材，请补充原始资料。",
                            {"fields": [field], "status": "MATERIAL_REQUIRED"})
        if state.creative_mode == "planned":
            if not state.brief.fictional and not creative.primary_material(state.brief, state.materials):
                return Decision("ASK", "素材不能支持指定结果，请补充原始证据。",
                                {"fields": ["对应主体的结果证据"], "status": "MATERIAL_REQUIRED"})
            if not state.plans:
                return Decision("PLAN", "先提出两个有事实边界的创意方向。")
            if state.plan is None:
                plan_id, reason = self.select_concept(state.brief, state.plans)
                return Decision("SELECT_CONCEPT", reason, {"plan_id": plan_id})
        elif (state.brief.proof_id or state.brief.conversion_story) and not self._proof(state.brief, state.materials):
            return Decision("ASK", "缺少可拍的操作，或素材未显示 Brief 中要求的结果。",
                            {"fields": ["操作画面及结果证据"], "status": "MATERIAL_REQUIRED"})
        if state.draft is None:
            return Decision("WRITE", "按可用依据起草中文文案。")
        if not state.scenes:
            return Decision("DIRECT", "把文案编排成可拍的分镜。",
                            {"compact": state.duration_revisions > 0})
        if state.quality is None:
            return Decision("CHECK", "估算当前版本时长并检查品牌约束。")
        duration = state.quality["duration"]
        if not state.quality["brand"]["passed"]:
            issues = state.quality["brand"]["issues"]
            if (state.revisions < 2 and issues
                    and all(issue["code"] == "REQUIRED_TERM_MISSING" for issue in issues)
                    and disclosure_sources(issues, state.materials)):
                return Decision("ADD_DISCLOSURE", "必说项可由现有素材支持，补入出处镜头后重新排镜和检查。")
            if state.brief.production and state.revisions == 0 and all(
                issue["field"] == "title" and issue["code"] == "BANNED_TERM" for issue in issues
            ):
                return Decision("REPAIR_TITLE", "禁用词只出现在标题，删去该表述后重查时长与规则。")
            return Decision("STOP", "规则或事实证据未通过，请按检查结果补充依据或改稿。",
                            {"status": "QUALITY_FAILED"})
        if not state.quality['grounding']['passed']:
            beats = {b.id:b for b in state.draft.beats}
            editable = all((i['scene_id']=='title' and getattr(self,'creative_model_mode','mock')=='llm') or
                (i['scene_id'] in beats and not creative.creative_lock(state.brief,beats[i['scene_id']],i['field']))
                for i in state.quality['grounding']['issues'])
            if editable and (state.brief.creative_policy == 'reference' or getattr(self,'creative_model_mode','mock')=='llm'):
                return Decision('REPAIR_UNVERIFIED', '参考文本有未核验字段，替换为受控创意后重新检查。')
            return Decision('STOP', '存在无法核验的自由表述；请补充原文依据或将可修改内容标为参考。',
                            {'status': 'NEEDS_REVIEW'})
        if not duration["passed"]:
            if state.duration_revisions or state.brief.target_seconds < sum(
                    scene.minimum_visual_seconds for scene in state.scenes):
                return Decision("STOP", "当前预算无法容纳有效画面和口播。",
                                {"status": "DURATION_UNMET"})
            ids = tuple(row["scene_id"] for row in duration["scenes"]
                        if row["spoken_seconds"] > row["minimum_visual_seconds"]
                        or row["reading_seconds"] > row["minimum_visual_seconds"])
            if state.creative_mode == "planned":
                by_id = {scene.beat.id: scene.beat for scene in state.scenes}
                ids = tuple(key for key in ids if not creative.creative_lock(state.brief, by_id[key], "voiceover")
                            and not creative.creative_lock(state.brief, by_id[key], "subtitle"))
            if ids and not state.brief.production:
                return Decision("REVISE_COPY", "口播或字幕占用时间，压缩指定镜头再重新排镜。",
                                {"scene_ids": list(ids)})
            if state.brief.production:
                long_hooks = [
                    scene.beat.id for scene, timing in zip(state.scenes, duration["scenes"], strict=True)
                    if scene.beat.purpose in {"hook", "turn"}
                    and timing["spoken_seconds"] > timing["planned_seconds"]
                    and self._first_sentence(scene.beat.voiceover) != scene.beat.voiceover
                    and (state.creative_mode == "legacy" or not creative.creative_lock(state.brief, scene.beat, "voiceover"))
                ]
                if long_hooks:
                    return Decision("REVISE_COPY", "开场口播超出镜头预算，删减后段铺垫并保留商品证据。",
                                    {"scene_ids": long_hooks})
                return Decision("COMPACT_SCENES", "保留开场、操作和结果，缩短镜头停留后重新估时。")
            return Decision("COMPACT_SCENES", "口播可容纳，调整镜头停留时长。")
        if state.review is None:
            return Decision("REVIEW", "时长和规则通过，核对事实、画面与镜头承接。")
        if not state.review["passed"]:
            if any(issue["code"] == "SALES_STORY_INCOMPLETE" for issue in state.review["issues"]):
                return Decision("STOP", "剧情带货稿缺少独立的转折或人物结局，请先改稿。",
                                {"status": "QUALITY_FAILED"})
            return Decision("STOP", "审核发现需人工补证或修正的问题。",
                            {"status": "QUALITY_FAILED"})
        if state.creative_mode == "planned":
            if state.creative_review is None:
                return Decision("CRITIQUE", "检查开场期待、人物动机、收尾兑现和重复解释，给出逐镜修改目标。")
            if not state.creative_review["passed"]:
                issues = state.creative_review["issues"]
                beats = {beat.id: beat for beat in state.draft.beats}
                if any(creative.creative_lock(state.brief, beats[issue["scene_id"]], issue["field"]) for issue in issues):
                    return Decision("STOP", "创作问题涉及用户锁定内容或事实镜头，请确认修改要求。", {"status": "QUALITY_FAILED"})
                return Decision("REWRITE_CREATIVE", "按评审定位重写目标字段，保留事实、优惠条件和转化入口。")
        return Decision("DELIVER", "当前版本的硬性检查与适用的创作诊断均通过。")

    def propose_concepts(self, brief, materials):
        return creative.propose(brief, materials)

    def select_concept(self, brief, plans):
        return creative.select(brief, plans)

    def write_concept(self, brief, plan, materials):
        return creative.write(brief, plan, materials)

    def critique(self, brief, plan, draft, scenes):
        return creative.critique(brief, plan, draft, scenes)

    def rewrite_creative(self, brief, plan, draft, issues):
        return creative.rewrite(brief, plan, draft, issues)

    def props(self, brief: Brief, query: str) -> tuple[str, str]:
        return brief.subject, query

    def screenwriter(self, brief: Brief, materials: tuple[Material, ...]) -> Draft:
        if brief.production:
            return self._production_draft(brief, materials)
        if brief.fictional:
            return Draft(f"{brief.topic}｜原创短剧情", (
                Beat("S01", "setup", "同一位主角站在门口，手里攥着一张便签。",
                     "门口很安静。要把这张便签交给对方吗？"),
                Beat("S02", "payoff", "主角把手中的便签递给对方，镜头跟住这张便签。",
                     "还是当面说吧。这句话，我想了很久。"),
                Beat("S03", "close", "对方接过便签，主角松开手。",
                     "说出口以后，主角终于笑了。"),
            ))
        item = materials[0]
        openings = {
            "demo": ("这个功能怎么用？", "先看一遍完整的操作，再留意画面里的结果。"),
            "tutorial": ("这一步怎么做？", "我们从操作前的画面开始，然后看清关键一步。"),
            "story": ("接下来会发生什么？", "人物停下来，注意力落到这个操作上。"),
        }
        question, detail = openings[brief.format]
        return Draft(f"{brief.topic}｜{item.subject}", (
            Beat("S01", "setup", "给出使用前的场景，把注意力引到接下来的操作。",
                 f"{question}{detail}"),
            Beat("S02", "payoff", item.visual, item.fact.rstrip("。") + "。", material_id=item.id),
            Beat("S03", "close", "保留结果画面，留出结尾停顿。",
                 "看清刚才的动作之后，可以暂停回看这一段。"),
        ))

    @staticmethod
    def _proof(brief: Brief, materials: tuple[Material, ...]) -> Material | None:
        return next((item for item in materials if item.operation
                     and (not brief.proof_id or item.id == brief.proof_id)
                     and normalized(brief.visible_result) in normalized(item.visual)), None)

    @staticmethod
    def _story_seed(brief: Brief) -> tuple[str, str, str, str, str]:
        seeds = {
            "purchase": ("主角抬手正要收起样品，同伴按住盒盖。", "等一下，这款你看清了吗？",
                         "同伴把注意力从外盒转到商品细节。", "主角看过样品细节，把它留在面前。"),
            "store_visit": ("一人已经转身要走，朋友叫住他。", "先别走，要不要进去看看？",
                           "两人停在门口，决定先看一眼店里的样品。", "两人收起手机，转身走进门店。"),
            "lead": ("一人刚要划走，朋友伸手挡了一下。", "这个细节你刚才看清了吗？",
                     "两人停下来，把想弄清楚的问题写在便签上。", "主角拿起手机，准备咨询便签上的问题。"),
            "event_signup": ("同伴拿上包准备出门，主角把他叫住。", "你选好场次了吗？",
                             "同伴停下脚步，两人先看活动样品。", "两人对视点头，低头打开预约入口。"),
            "brand_awareness": ("两人在整理桌面，其中一人把样品推到对方面前。", "这个你见过吗？",
                                "另一人停下手里的动作，低头看样品。", "两人看完，一人把样品留在桌面中央。"),
            "product_understanding": ("主角拿起样品，转到另一面。", "这个位置是做什么的？",
                                      "同伴伸手指出需要观察的位置。", "主角回到原来的位置，自己重复刚才看到的动作。"),
        }
        opening, line, turn, resolution = seeds.get(brief.goal, seeds["purchase"])
        if brief.goal == "store_visit" and brief.conversion_action == "claim_coupon":
            resolution = "两人留在门口，主角拿出手机，示意先领券再进去。"
        return (brief.opening or opening, brief.hook_line or line, brief.turn or turn,
                brief.turn_line, brief.resolution or resolution)

    @staticmethod
    def _production_draft(brief: Brief, materials: tuple[Material, ...]) -> Draft:
        beats = []

        def add(purpose, action, voiceover="", subtitle="", material_id=""):
            beats.append(Beat(f"S{len(beats) + 1:02d}", purpose, action, voiceover, subtitle, material_id))

        opening, line, turn, turn_line, resolution = MockModels._story_seed(brief)
        if not brief.conversion_story:
            opening = brief.opening or f"对准{brief.subject}，让商品关键位置进入画面。"
            line = brief.hook_line
        location = f"{brief.setting.rstrip('。')}。" if brief.setting else ""
        add("hook", f"{location}{opening.rstrip('。')}。", line)
        if brief.conversion_story:
            add("turn", turn, turn_line)
        if brief.fictional:
            add("payoff", brief.visible_result)
        else:
            item = MockModels._proof(brief, materials) or materials[0]
            if item.operation and brief.format != "talking_head":
                add("operation", item.operation, material_id=item.id)
            add("payoff", item.visual, item.fact.rstrip("。") + "。", material_id=item.id)
        if brief.conversion_story:
            add("resolution", resolution, subtitle=brief.resolved_cta)
        elif brief.resolved_cta:
            add("cta", "定格上一镜的结果，在空白安全区叠加引导文字。",
                subtitle=brief.resolved_cta, material_id=beats[-1].material_id)
        if not any(beat.voiceover or beat.subtitle for beat in beats):
            beats[0] = replace(beats[0], subtitle=brief.topic)
        return Draft(brief.topic, tuple(beats))

    @staticmethod
    def _first_sentence(text: str) -> str:
        return re.split(r"(?<=[。！？])", text, maxsplit=1)[0]

    def revise_copy(self, draft: Draft, scene_ids: tuple[str, ...]) -> Draft:
        short = {"setup": "先看这里。", "payoff": "给你。", "close": "看结果。"}
        beats = []
        for beat in draft.beats:
            if beat.id in scene_ids and not beat.material_id and beat.purpose in {"hook", "turn"}:
                beat = replace(beat, voiceover=self._first_sentence(beat.voiceover))
            elif beat.id in scene_ids and not beat.material_id and beat.purpose in short:
                question, mark, _ = beat.voiceover.partition("？")
                voiceover = question + mark if beat.purpose == "setup" and mark else short[beat.purpose]
                beat = replace(beat, voiceover=voiceover, subtitle="")
            beats.append(beat)
        return replace(draft, beats=tuple(beats))

    def director(self, brief: Brief, draft: Draft, compact: bool) -> tuple[Scene, ...]:
        if brief.production:
            return self._production_scenes(brief, draft, compact)
        plans = {"setup": (7, 2), "payoff": (9, 4), "close": (6, 2), "disclaimer": (4, 2)}
        minimum = sum(plans[beat.purpose][1] for beat in draft.beats)
        extra = min(4, max(0, brief.target_seconds - minimum))
        scenes = []
        for beat in draft.beats:
            planned, floor = plans[beat.purpose]
            if compact:
                planned = floor
                if beat.purpose == "payoff":
                    planned += extra
                    extra = 0
            continuity = "沿用同一人物与便签" if brief.fictional else "保持同一主体及操作前后的画面对应"
            scenes.append(Scene(beat, planned, floor, continuity))
        return tuple(scenes)

    @staticmethod
    def _production_scenes(brief: Brief, draft: Draft, compact: bool) -> tuple[Scene, ...]:
        shots = {
            "turn": (4, 2, "反打人物反应，交代改变动作的原因", "台词跟随动作", "在人物转向时切镜"),
            "resolution": (5, 3, "回到开场构图，拍完人物行动", "保留现场声", "动作完成后再叠引导"),
            "disclaimer": (4, 2, "规则原文特写，保留完整适用条件", "口播完整说明适用条件", "读完后切回收尾"),
            "hook": (5, 2, "近景，动作落在画面中心", "先留现场声，再进开场台词", "在动作最清楚处切入"),
            "operation": (8, 3, "操作特写，保留手势或光标的完整路径", "保留同期声，静音录屏保持无声",
                          "在操作开始时切入，保留触发瞬间"),
            "payoff": (9, 4, "结果特写，关键细节留在安全区", "结果出现后再入口播，保留短停顿",
                       "延续上镜方向，让结果自然出现"),
            "cta": (4, 2, "沿用结果镜头，文字避开原字幕和操作结果", "同期声渐弱",
                    "结果定格后淡入字幕"),
        }
        if brief.conversion_story:
            shots.update(
                hook=(3, 2, "近景，从人物正在做的动作切入", "先入现场声，台词跟动作走", "在动作中切出"),
                turn=(4, 2, "反打人物反应，保留阻碍所在的位置", "停半拍后接转折台词", "在人物转向解决动作时切出"),
                operation=(5, 2, "切手部特写，交代关键一步", "保留动作同期声", "跟动作切到结果"),
                payoff=(6, 3, "特写保留素材里的可见结果", "结果出现后接商品事实口播", "回切人物与原场景"),
                resolution=(5, 3, "拉回人物，拍完决定与行动", "保留现场声", "动作完成后再叠商品卡引导"),
            )
        available = brief.target_seconds - sum(shots[beat.purpose][1] for beat in draft.beats)
        extra = {}
        if compact:
            minimum = {beat.id: max(shots[beat.purpose][1], *text_seconds(beat)) for beat in draft.beats}
            spare = max(0, brief.target_seconds - sum(minimum.values()))
            for beat in draft.beats:
                if beat.purpose in {"operation", "payoff"}:
                    # Reserve space for unchanged opening and CTA copy.
                    extra[beat.id] = max(0, min(shots[beat.purpose][0] - minimum[beat.id],
                                                (available - 2) // 2, spare))
                    spare -= extra[beat.id]
        scenes = []
        for beat in draft.beats:
            plan, floor, frame, sound, transition = shots[beat.purpose]
            if brief.format == "talking_head" and beat.purpose == "hook":
                frame = "正面中近景，人物面对镜头"
            if "快节奏" in brief.style:
                transition = "动作完成即切，避免额外停顿"
            if "克制" in brief.style or "安静" in brief.style:
                sound = "轻留现场声，避免突兀音效"
            if not beat.voiceover and beat.purpose in {"hook", "payoff"}:
                sound = "保留现场声，给动作留停顿"
            continuity = "沿用开场人物、物件和动作方向" if brief.fictional else (
                f"保持主体一致（{brief.subject}），证据镜头沿用同一次操作的原顺序"
            )
            revised = minimum[beat.id] + extra.get(beat.id, 0) if compact else plan
            scenes.append(Scene(beat, revised, floor,
                                continuity, frame, sound, transition))
        return tuple(scenes)

    def reviewer(self, brief: Brief, draft: Draft, scenes: tuple[Scene, ...],
                 materials: tuple[Material, ...]) -> dict:
        sources = {item.id: item for item in materials}
        issues = []
        if not any(scene.beat.purpose == "payoff" for scene in scenes):
            issues.append({"scene_id": "", "field": "purpose", "code": "MISSING_PAYOFF"})
        if brief.conversion_story:
            beats = [scene.beat for scene in scenes if scene.beat.purpose != "disclaimer"]
            expected = ["hook", "turn", "operation", "payoff", "resolution"]
            opening, _, turn, _, resolution = self._story_seed(brief)
            actions = {normalized(beat.action).rstrip("。！？") for beat in beats}
            if ([beat.purpose for beat in beats] != expected or len(actions) != len(expected)
                    or opening.rstrip("。") not in beats[0].action
                    or beats[1].action != turn or beats[4].action != resolution
                    or beats[4].subtitle != brief.resolved_cta):
                issues.append({"scene_id": "", "field": "scenes", "code": "SALES_STORY_INCOMPLETE"})
        for scene in scenes:
            beat = scene.beat
            if beat.purpose == "operation" and not brief.fictional:
                source = sources.get(beat.material_id)
                if source is None or (brief.proof_id and beat.material_id != brief.proof_id) or beat.action != source.operation:
                    issues.append({"scene_id": beat.id, "field": "action", "code": "OPERATION_MISMATCH"})
            if beat.purpose not in {"payoff", "disclaimer"} or brief.fictional:
                continue
            source = sources.get(beat.material_id)
            fact = source.fact.rstrip("。") if source else ""
            if source is None or not all((beat.action == source.visual,
                                          beat.voiceover.rstrip("。") == fact,
                                          not beat.subtitle or beat.subtitle.rstrip("。") == fact)):
                issues.append({"scene_id": beat.id, "field": "action/voiceover/subtitle",
                               "code": "EVIDENCE_MISMATCH", "material_id": beat.material_id})
            if beat.purpose == "payoff" and brief.proof_id and (beat.material_id != brief.proof_id or
                                     normalized(brief.visible_result) not in normalized(beat.action)):
                issues.append({"scene_id": beat.id, "field": "action", "code": "MISSING_VISIBLE_RESULT"})
        if brief.goal in GOAL_ACTIONS and not any(scene.beat.purpose in {"cta", "resolution"}
                                                 and scene.beat.subtitle == brief.resolved_cta for scene in scenes):
            issues.append({"scene_id": "", "field": "conversion", "code": "CTA_MISMATCH"})
        if brief.production and [scene.beat for scene in scenes] != list(draft.beats):
            issues.append({"scene_id": "", "field": "scenes", "code": "STORYBOARD_SEQUENCE_CHANGED"})
        scope = "Mock 核对素材与兑现镜头"
        if brief.conversion_story:
            scope += "，检查独立转折及人物结局"
        return {"passed": not issues, "issues": issues, "scope": scope}
