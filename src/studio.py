"""Run the studio and record observations from actual tool executions."""
import re
import hashlib
import json
from time import perf_counter
from uuid import uuid4
from dataclasses import asdict, replace
from typing import Callable

from .models import StudioModels
from . import creative, grounding
from .contracts import (ContractError, decision_contract, draft_contract, duration_contract,
                        materials_contract, report_contract, require, scenes_contract,
                        plans_contract, locked_creative_contract, creative_report_contract, creative_revision_contract, grounding_revision_contract)
from .schema import Beat, Brief, Decision, InputError, ModelError, State
from .tools import LocalTools, ToolError, material_summary

LABELS = {
    "COMPLETED": "已完成",
    "NEEDS_INPUT": "待补充需求",
    "MATERIAL_REQUIRED": "待补充素材",
    "TOOL_FAILED": "工具失败",
    "MODEL_FAILED": "模型决策失败",
    "NEEDS_REVIEW": "存在未核验内容",
    "QUALITY_FAILED": "质量检查未通过",
    "DURATION_UNMET": "无法满足时长",
    "STEP_LIMIT": "达到步骤上限",
    "TOOL_LIMIT": "达到工具调用上限",
    "REVISION_LIMIT": "达到修订上限",
    "INVALID_ACTION": "动作校验失败",
    "INVALID_INPUT": "输入无效",
}
DEFAULT_STEPS = 20
DEFAULT_TOOL_CALLS = 10
MAX_REVISIONS = 2


class InvalidAction(RuntimeError):
    pass


class ToolLimit(RuntimeError):
    pass


class InvalidToolResult(RuntimeError):
    pass


class Studio:
    def __init__(self, models: StudioModels, tools: LocalTools, max_steps: int = DEFAULT_STEPS,
                 max_tool_calls: int = DEFAULT_TOOL_CALLS, creative_mode: str = "planned"):
        if any(type(value) is not int or value <= 0 for value in (max_steps, max_tool_calls)):
            raise InputError("步骤与工具调用上限必须为正整数。")
        if creative_mode not in {"planned", "legacy"}:
            raise InputError("创作模式仅支持 planned 或 legacy。")
        self.creative_mode = creative_mode
        self.models = models
        if hasattr(models,"model_calls"):
            models.runtime_rules={"banned_terms":list(tools.banned),"required_terms":list(tools.required)}
        self.tools = tools
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls

    def run(self, raw: object) -> dict:
        if hasattr(self.models,"begin_run"):
            self.models.begin_run()
        started = perf_counter()
        run_id = uuid4().hex
        brief, missing = Brief.parse(raw)
        state = State(brief, missing, creative_mode=self.creative_mode)
        trace = []

        def finish(code: str, detail: str, fields: list[str] | None = None) -> dict:
            script = self._final_script(state) if code == "COMPLETED" else None
            calls = getattr(self.models, "model_calls", [])
            for event in trace:
                event["model_calls"] = [c for c in calls if c["step"] == event["step"]]
            return {"model_mode": self.models.mode, "status": code, "status_text": LABELS[code],
                    "detail": detail, "requested_fields": fields or [], "script": script,
                    "script_version": state.version, "revision_count": state.revisions,
                    "checks": self._checks(state),
                    "creative_mode": state.creative_mode, "creative_model_mode": getattr(self.models, "creative_model_mode", "unknown"),
                    "creative": {"plans": [asdict(plan) for plan in state.plans],
                                 "selected_plan_id": state.plan.id if state.plan else None,
                                 "selection_reason": state.selection_reason,
                                 "revision_count": state.creative_revisions,
                                 "evidence_pack": creative.evidence_pack(state.materials)},
                    "audit": {"run_id": run_id, "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                              "tool_calls": state.tool_calls, "max_tool_calls": self.max_tool_calls,
                              "model_calls": len(calls),
                              "steps": len(trace), "max_steps": self.max_steps,
                              "input_sha256": self._digest(raw),
                              "materials_sha256": self._digest(material_summary(self.tools.materials)),
                              "grounding_policy": "semantic-v2" if getattr(self.models,"creative_model_mode","mock")=="llm" else grounding.POLICY_VERSION,
                              "rules_sha256": self._digest({"banned": self.tools.banned,
                                                            "required": self.tools.required})},
                    "decision_model": {"name": getattr(self.models, "model_name", "offline"),
                                       "transport": getattr(self.models, "transport", "offline")},
                    "llm_decisions": sum(event.get("decision_source") == "llm" for event in trace),
                    "trace": trace}

        for step in range(1, self.max_steps + 1):
            if hasattr(self.models, "current_step"):
                self.models.current_step = step
            try:
                decision = self.models.producer(state)
                decision_contract(decision)
            except (ModelError, ContractError) as exc:
                if trace:
                    trace[-1]["next_action"] = "MODEL_FAILED"
                trace.append({"step": step, "action": "MODEL_FAILED", "status": "terminal",
                              "model_mode": self.models.mode, "reason": str(exc),
                              "script_version": state.version, "calls": [], "next_action": "END"})
                return finish("MODEL_FAILED", str(exc))
            event = {"step": step, **asdict(decision), "model_mode": self.models.mode,
                     "script_version": state.version, "calls": []}
            if trace:
                trace[-1]["next_action"] = decision.action
            trace.append(event)
            action = decision.action
            try:
                if action == "ASK":
                    code = decision.args.get("status", "NEEDS_INPUT")
                    if code not in {"NEEDS_INPUT", "MATERIAL_REQUIRED"}:
                        raise InvalidAction("无效的澄清状态。")
                    event.update(status="terminal", next_action="END")
                    return finish(code, decision.reason, decision.args.get("fields"))
                if action == "STOP":
                    code = decision.args.get("status")
                    if code not in {"TOOL_FAILED", "QUALITY_FAILED", "DURATION_UNMET", "NEEDS_REVIEW"}:
                        raise InvalidAction("无效的停止状态。")
                    event.update(status="terminal", next_action="END")
                    return finish(code, decision.reason)
                if action == "DELIVER":
                    if not self._can_deliver(state):
                        raise InvalidAction("当前版本尚未通过交付检查。")
                    event.update(status="terminal", next_action="END")
                    return finish("COMPLETED", decision.reason)
                if action in {"REVISE_COPY", "COMPACT_SCENES", "REPAIR_TITLE", "ADD_DISCLOSURE", "REWRITE_CREATIVE", "REPAIR_UNVERIFIED"} and state.revisions >= MAX_REVISIONS:
                    event.update(status="terminal", next_action="END")
                    return finish("REVISION_LIMIT", "已用完修订预算。")
                self._execute(state, decision, event)
            except ToolError:
                event["status"] = "tool_error"
            except ToolLimit:
                event.update(status="terminal", next_action="END")
                return finish("TOOL_LIMIT", "工具调用预算耗尽，当前任务未完成。")
            except InvalidToolResult as exc:
                event.update(status="rejected", error=str(exc), next_action="END")
                return finish("TOOL_FAILED", str(exc))
            except (ModelError, ContractError) as exc:
                event.update(status="model_error", error=str(exc), next_action="END")
                return finish("MODEL_FAILED", str(exc))
            except InvalidAction as exc:
                event.update(status="rejected", error=str(exc), next_action="END")
                return finish("INVALID_ACTION", str(exc))
            else:
                event["status"] = "ok"
            event["script_version_after"] = state.version
            state.last = event

        if trace:
            trace[-1]["next_action"] = "STEP_LIMIT"
        return finish("STEP_LIMIT", "达到步骤上限，当前任务未完成。")

    def _execute(self, state: State, decision: Decision, event: dict) -> None:
        brief, action, args = state.brief, decision.action, decision.args
        if brief is None:
            raise InvalidAction("关键需求缺失。")
        if action == "FIND_MATERIAL":
            props = self.models.props(brief, args.get("query", ""))
            require(isinstance(props, tuple) and len(props) == 2
                    and all(isinstance(value, str) for value in props), "道具返回的检索参数无效。")
            subject, query = props
            require(subject == brief.subject and len(query) <= 120, "道具不能更换事实主体或使用过长查询。")
            event["role"] = "道具"
            if brief.fictional:
                event["observation"] = {"evidence": "原创虚构剧情，无外部事实素材要求"}
            else:
                state.searches += 1
                params = {"subject": subject, "query": query}
                tool_args = (subject, query)
                if brief.proof_id:
                    params["material_id"] = brief.proof_id
                    tool_args += (brief.proof_id,)
                state.materials = self._invoke(state, event, "search_material",
                                               params, self.tools.search_material, *tool_args,
                                               summarize=material_summary,
                                               validate=lambda result: materials_contract(
                                                   result, self.tools.materials, subject, brief.proof_id))
            state.plans, state.plan = (), None
            state.draft, state.scenes = None, ()
            state.searched = True
            state.invalidate_checks()
            return
        if not state.searched or (not brief.fictional and not state.materials):
            raise InvalidAction("素材准备未完成。")
        if action == "PLAN":
            if state.creative_mode != "planned" or state.draft is not None:
                raise InvalidAction("只能在起稿前提出创意方案。")
            plans = self.models.propose_concepts(brief, state.materials)
            plans_contract(plans, brief, state.materials)
            state.plans, state.plan = plans, None
            event["role"] = "编剧"
            event["observation"] = {"plans": [asdict(plan) for plan in plans],
                                    "evidence_pack": creative.evidence_pack(state.materials)}
            return
        if action == "SELECT_CONCEPT":
            if state.draft is not None:
                raise InvalidAction("稿件生成后不能绕过修订门槛更换方案。")
            plan = next((plan for plan in state.plans if plan.id == args.get("plan_id")), None)
            if plan is None:
                raise InvalidAction("须选择已校验的创意方案。")
            state.plan, state.selection_reason = plan, decision.reason
            event["role"] = "制片人"
            event["observation"] = {"selected_plan_id": plan.id}
            return
        if state.creative_mode == "planned" and state.plan is None:
            raise InvalidAction("必须先选择有依据的创意方案。")
        if action == "WRITE":
            event["role"] = "编剧"
            draft = (self.models.write_concept(brief, state.plan, state.materials)
                     if state.creative_mode == "planned" else self.models.screenwriter(brief, state.materials))
            draft_contract(draft)
            if getattr(self.models,"creative_model_mode","mock") != "llm" and draft.title in {brief.topic, f"{brief.topic}｜{brief.subject}",
                               *(f"{brief.topic}｜{m.subject}" for m in state.materials),
                               f"{brief.topic}｜原创短剧情"}:
                draft = replace(draft, title=grounding.canonical_title(brief))
            draft_contract(draft)
            if state.creative_mode == "planned":
                locked_creative_contract(brief, draft)
            state.draft = draft
            state.scenes = ()
            state.invalidate_checks()
            event["observation"] = asdict(state.draft)
            return
        if state.draft is None:
            raise InvalidAction("文案尚未生成。")
        if action == "REPAIR_UNVERIFIED":
            if not state.quality or state.quality['grounding']['passed']:
                raise InvalidAction("只允许修订当前已定位的未核验参考内容。")
            issues = state.quality['grounding']['issues']
            handler = getattr(self.models, "repair_unverified", grounding.safe_replacement)
            draft = handler(brief, state.draft, state.materials, issues)
            grounding_revision_contract(brief, state.draft, draft, issues)
            state.draft, state.scenes = draft, ()
            state.revisions += 1
            state.invalidate_checks()
            event['role'] = '编剧'
            event['observation'] = {'removed_or_replaced': issues, 'draft': asdict(draft)}
            return
        if action == "REWRITE_CREATIVE":
            if not state.plan or not state.creative_review or state.creative_review["version"] != state.version:
                raise InvalidAction("创作修订需要当前版本的评审。")
            issues = state.creative_review["issues"]
            if not issues:
                raise InvalidAction("当前没有可定向修订的创作问题。")
            draft = self.models.rewrite_creative(brief, state.plan, state.draft, issues)
            creative_revision_contract(brief, state.draft, draft, issues)
            if draft == state.draft:
                event["observation"] = {"no_change": True, "issues": issues}
            else:
                event["observation"] = {"targets": issues, "draft": asdict(draft)}
            state.draft, state.scenes = draft, ()
            state.revisions += 1
            state.creative_revisions += 1
            state.invalidate_checks()
            event["role"] = "编剧"
            return
        if action == "ADD_DISCLOSURE":
            issues = state.quality["brand"]["issues"] if state.quality else []
            if not issues or any(issue["code"] != "REQUIRED_TERM_MISSING" for issue in issues):
                raise InvalidAction("补写只允许处理当前检查发现的必说项缺失。")
            from .models import disclosure_sources
            sources = disclosure_sources(issues, state.materials)
            if not sources:
                raise InvalidAction("必说项缺少可引用的事实依据。")
            beats = list(state.draft.beats)
            disclosures = []
            for source in sources:
                index = 1
                used = {beat.id for beat in (*beats, *disclosures)}
                while f"D{index:02d}" in used:
                    index += 1
                disclosures.append(Beat(f"D{index:02d}", "disclaimer", source.visual,
                                        source.fact, source.fact, source.id))
            # Keep the original resolution/CTA last; do not replace product proof.
            beats[-1:-1] = disclosures
            draft = replace(state.draft, beats=tuple(beats))
            draft_contract(draft)
            state.draft = draft
            state.scenes = ()
            state.revisions += 1
            state.invalidate_checks()
            event["role"] = "编剧"
            event["observation"] = asdict(draft)
            return
        if action == "REPAIR_TITLE":
            issues = state.quality["brand"]["issues"] if state.quality else []
            if not issues or any(issue["field"] != "title" or issue["code"] != "BANNED_TERM" for issue in issues):
                raise InvalidAction("标题改稿只允许移除当前检查发现的标题禁用词。")
            title = state.draft.title
            for issue in issues:
                title = re.sub(re.escape(issue["value"]), "", title, flags=re.IGNORECASE)
            title = title.strip(" 　，,。｜|：:！!－-")
            if not title or title == state.draft.title:
                raise InvalidAction("无法安全移除标题禁用词。")
            state.draft = replace(state.draft, title=title)
            state.revisions += 1
            state.version += 1
            state.invalidate_checks()
            event["role"] = "编剧"
            event["observation"] = {"title": title}
            return
        if action == "REVISE_COPY":
            if not state.scenes:
                raise InvalidAction("缺少待修订的分镜。")
            ids = tuple(args.get("scene_ids", ()))
            if not ids or not set(ids) <= {beat.id for beat in state.draft.beats}:
                raise InvalidAction("修订必须引用有效镜头编号。")
            event["role"] = "编剧"
            draft = self.models.revise_copy(state.draft, ids)
            draft_contract(draft)
            if (len(draft.beats) != len(state.draft.beats) or draft.title != state.draft.title
                    or any(new.id != old.id or (new != old and old.id not in ids)
                           for old, new in zip(state.draft.beats, draft.beats))):
                raise InvalidAction("定向修订不得修改非目标镜头、标题或镜头顺序。")
            if state.creative_mode == "planned":
                targets = [{"scene_id": key, "field": field} for key in ids for field in ("voiceover", "subtitle")]
                creative_revision_contract(brief, state.draft, draft, targets)
            state.draft = draft
            state.revisions += 1
            state.duration_revisions += 1
            state.scenes = ()
            state.invalidate_checks()
            event["observation"] = asdict(state.draft)
            return
        if action in {"DIRECT", "COMPACT_SCENES"}:
            if action == "COMPACT_SCENES" and not state.scenes:
                raise InvalidAction("缺少待压缩的分镜。")
            event["role"] = "导演"
            compact = action == "COMPACT_SCENES" or args.get("compact", False)
            directing_brief = creative.effective_brief(brief, state.plan) if state.plan else brief
            scenes = self.models.director(directing_brief, state.draft, compact)
            scenes_contract(scenes)
            require(tuple(s.beat for s in scenes) == state.draft.beats, "导演不能替换文案或镜头顺序。")
            if action == "COMPACT_SCENES":
                state.revisions += 1
                state.duration_revisions += 1
            state.scenes = scenes
            state.version += 1
            state.invalidate_checks()
            event["observation"] = {"scenes": [asdict(scene) for scene in scenes]}
            return
        if not state.scenes:
            raise InvalidAction("分镜尚未生成。")
        if action == "CHECK":
            event["role"] = "质量工具"
            state.invalidate_checks()
            duration = self._invoke(
                state, event, "estimate_duration", {"target_seconds": brief.target_seconds,
                                             "scenes": [asdict(scene) for scene in state.scenes]},
                self.tools.estimate_duration, state.scenes, brief.target_seconds,
                validate=lambda result: duration_contract(result, state.scenes, brief.target_seconds))
            brand = self._invoke(
                state, event, "check_brand", {"title": state.draft.title,
                                       "scenes": [asdict(scene) for scene in state.scenes],
                                       "material_ids": [item.id for item in state.materials],
                                       "banned_terms": list(self.tools.banned),
                                       "required_terms": list(self.tools.required)},
                self.tools.check_brand, state.draft, state.scenes, state.materials,
                validate=report_contract)
            ledger = getattr(self.models, "grounding", grounding.inspect)(brief, state.draft, state.scenes, state.materials)
            event['observation'] = {'grounding': ledger}
            state.quality = {"version": state.version, "duration": duration, "brand": brand, 'grounding': ledger}
            return
        if action == "REVIEW":
            event["role"] = "审核"
            reviewing_brief = replace(brief, format="demo", objective=brief.objective or "创作检查") if state.plan else brief
            review = self.models.reviewer(reviewing_brief, state.draft, state.scenes, state.materials)
            if state.plan:
                locked_creative_contract(brief, state.draft)
                if brief.format in {"story", "sales_story"}:
                    purposes = [scene.beat.purpose for scene in state.scenes if scene.beat.purpose != "disclaimer"]
                    expected = ["hook", "turn"] + (["operation"] if "operation" in purposes else []) + ["payoff", "resolution"]
                    reduced = [p for i,p in enumerate(purposes) if i==0 or p!=purposes[i-1]]
                    if reduced != expected:
                        review = {"passed": False, "issues": [{"scene_id": "", "field": "scenes", "code": "SALES_STORY_INCOMPLETE"}]}
            report_contract(review)
            state.review = {
                **review,
                "version": state.version,
            }
            event["observation"] = state.review
            return
        if action == "CRITIQUE":
            if (not state.plan or not state.quality or not state.review or not state.review["passed"]
                    or state.quality["version"] != state.review["version"] or state.review["version"] != state.version
                    or not state.quality["duration"]["passed"] or not state.quality["brand"]["passed"]
                    or not state.quality["grounding"]["passed"]):
                raise InvalidAction("创作诊断需要方案及当前硬性审核。")
            report = self.models.critique(brief, state.plan, state.draft, state.scenes)
            creative_report_contract(report, state.draft)
            state.creative_review = {**report, "version": state.version}
            event["role"] = "创作审核"
            event["observation"] = state.creative_review
            return
        raise InvalidAction(f"未知动作 {action}。")

    def _invoke(self, state: State, event: dict, tool: str, params: dict, handler: Callable, *args,
                summarize: Callable = lambda result: result, validate: Callable = lambda result: None):
        if state.tool_calls >= self.max_tool_calls:
            raise ToolLimit()
        state.tool_calls += 1
        call = {"tool": tool, "params": params}
        event["calls"].append(call)
        try:
            result = handler(*args)
            validate(result)
        except ContractError as exc:
            call["result"] = {"status": "error", "code": "INVALID_TOOL_RESULT", "detail": str(exc)}
            raise InvalidToolResult(str(exc)) from exc
        except OSError as exc:
            # Do not expose endpoint URLs, credentials or raw provider errors.
            call["result"] = {"status": "error", "code": "TOOL_UNAVAILABLE", "detail": "工具连接或读取失败。"}
            raise ToolError("工具连接或读取失败。") from exc
        except ToolError as exc:
            call["result"] = {"status": "error", "detail": str(exc)}
            raise
        call["result"] = summarize(result)
        return result

    @staticmethod
    def _digest(value) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _can_deliver(state: State) -> bool:
        quality, review = state.quality, state.review
        return bool(state.scenes and quality and review
                    and quality["version"] == review["version"] == state.version
                    and quality["duration"]["passed"] and quality["brand"]["passed"] and quality["grounding"]["passed"]
                    and review["passed"]
                    and (state.creative_mode == "legacy" or (state.plan and state.creative_review
                         and state.creative_review["version"] == state.version and state.creative_review["passed"])))

    @staticmethod
    def _checks(state: State) -> dict:
        return {"version": state.version, "duration": (state.quality or {}).get("duration"),
                "rules_and_claims": (state.quality or {}).get("brand"), "grounding": (state.quality or {}).get("grounding"), "review": state.review, "creative_review": state.creative_review}

    def _final_script(self, state: State) -> dict:
        duration = state.quality["duration"]
        scenes = []
        cursor = 0
        sources = {item.id: item for item in state.materials}
        for scene, timing in zip(state.scenes, duration["scenes"], strict=True):
            beat = scene.beat
            seconds = timing["estimated_seconds"]
            provenance = [row for row in state.quality['grounding']['records'] if row['scene_id'] == beat.id]
            ids = sorted({ref for row in provenance for ref in row['material_ids']} |
                         ({beat.material_id} if beat.material_id else set()))
            evidence = [{'material_id': ref, 'source': sources[ref].source, 'fact': sources[ref].fact}
                        for ref in ids]
            scenes.append({"id": beat.id, "purpose": beat.purpose, "visual": beat.action,
                           "voiceover": beat.voiceover, "start_seconds": cursor,
                           "end_seconds": cursor + seconds,
                           "subtitle": beat.subtitle, "planned_seconds": scene.planned_seconds,
                           "estimated_seconds": seconds,
                           "material_ids": ids,
                           "source": "；".join(sources[ref].source for ref in ids),
                           "evidence": evidence, "field_provenance": provenance,
                           "checks": {"rules_and_claims": "通过", "review": "通过",
                                      "spoken_seconds": timing["spoken_seconds"],
                                      "reading_seconds": timing["reading_seconds"]},
                           "framing": scene.framing, "sound": scene.sound,
                           "transition": scene.transition, "continuity": scene.continuity})
            cursor += seconds
        risks = (["发布前复核剧情衔接与产品主张。"] if state.plan else []) + ["估算时长需通过试读校准。"]
        if any(scene["material_ids"] for scene in scenes):
            risks.append("拍摄前确认素材真实性、画面可用性和适用条件。")
        return {"language": "zh-CN", "title": state.draft.title,
                "title_provenance": [r for r in state.quality["grounding"]["records"] if r["field"] == "title"],
                "audience": state.brief.audience, "platform": state.brief.platform,
                "goal": state.brief.goal, "campaign": state.brief.campaign,
                "format": state.brief.format, "format_policy": state.brief.format_policy,
                "conversion": {"action": state.brief.conversion_action,
                               "destination": state.brief.conversion_destination},
                "production": bool(state.plan) or state.brief.production,
                "style": state.brief.style,
                "objective": state.brief.objective,
                "target_seconds": state.brief.target_seconds, "aspect_ratio": state.brief.aspect_ratio,
                "estimated_seconds": duration["total_seconds"], "scenes": scenes,
                "material_ids": sorted({ref for scene in scenes for ref in scene["material_ids"]}),
                "risks": risks}
