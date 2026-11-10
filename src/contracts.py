"""Fail closed at model/tool boundaries before results reach the producer."""
from .schema import Beat, Decision, Draft, Material, Scene
from .tools import text_seconds


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def decision_contract(value) -> None:
    require(isinstance(value, Decision), "制片人必须返回决策对象。")
    require(isinstance(value.action, str) and isinstance(value.reason, str)
            and bool(value.reason.strip()) and isinstance(value.args, dict)
            and value.decision_source in ("mock", "llm"), "决策字段不合法。")
    args = value.args
    if "query" in args:
        require(isinstance(args["query"], str) and len(args["query"]) <= 120, "检索词不合法。")
    if "scene_ids" in args:
        require(isinstance(args["scene_ids"], (list, tuple))
                and all(isinstance(item, str) for item in args["scene_ids"]), "镜头编号不合法。")
    if "fields" in args:
        require(isinstance(args["fields"], list)
                and all(isinstance(item, str) for item in args["fields"]), "追问字段不合法。")
    for name in ("retry", "compact"):
        if name in args:
            require(type(args[name]) is bool, "动作标记必须为布尔值。")
    if "status" in args:
        require(isinstance(args["status"], str), "状态码不合法。")


def draft_contract(draft) -> None:
    require(isinstance(draft, Draft), "编剧必须返回脚本对象。")
    require(isinstance(draft.title, str) and bool(draft.title.strip())
            and isinstance(draft.beats, tuple) and 0 < len(draft.beats) <= 30, "脚本标题或镜头数量不合法。")
    for beat in draft.beats:
        require(isinstance(beat, Beat), "脚本镜头类型不合法。")
        require(all(isinstance(getattr(beat, name), str) for name in
                    ("id", "purpose", "action", "voiceover", "subtitle", "material_id")), "镜头字段必须是字符串。")
        require(bool(beat.id.strip() and beat.purpose.strip() and beat.action.strip()), "镜头编号、用途和画面不能为空。")
        require(beat.purpose in {"setup", "payoff", "close", "hook", "turn", "operation",
                                 "resolution", "cta", "disclaimer"}, "镜头用途不在当前导演支持范围内。")
    require(len({beat.id for beat in draft.beats}) == len(draft.beats), "镜头编号不能重复。")


def scenes_contract(scenes) -> None:
    require(isinstance(scenes, tuple) and bool(scenes), "导演必须返回非空分镜。")
    require(all(isinstance(scene, Scene) for scene in scenes), "分镜类型不合法。")
    draft_contract(Draft("分镜校验", tuple(scene.beat for scene in scenes)))
    for scene in scenes:
        require(type(scene.planned_seconds) is int and type(scene.minimum_visual_seconds) is int
                and 0 < scene.minimum_visual_seconds <= scene.planned_seconds, "分镜时长须为有效正整数。")
        require(all(isinstance(getattr(scene, name), str) for name in
                    ("continuity", "framing", "sound", "transition")), "拍摄说明必须为字符串。")
    require(any(scene.beat.voiceover or scene.beat.subtitle for scene in scenes), "分镜缺少旁白或字幕。")


def report_contract(report) -> None:
    require(isinstance(report, dict) and type(report.get("passed")) is bool
            and isinstance(report.get("issues"), list), "检查报告缺少有效状态或问题列表。")
    require(report["passed"] == (not report["issues"]), "检查结论与问题列表不一致。")
    for issue in report["issues"]:
        require(isinstance(issue, dict) and all(isinstance(issue.get(key), str)
                for key in ("scene_id", "field", "code")), "检查问题缺少镜头、字段或错误码。")
        if "value" in issue:
            require(isinstance(issue["value"], str), "检查问题的原文必须为字符串。")
        if issue["code"] in {"BANNED_TERM", "REQUIRED_TERM_MISSING"}:
            require(isinstance(issue.get("value"), str) and bool(issue["value"].strip()), "词语检查缺少有效原文。")


def duration_contract(report, scenes, target) -> None:
    require(isinstance(report, dict) and type(report.get("passed")) is bool
            and report.get("target_seconds") == target
            and isinstance(report.get("scenes"), list), "估时报告结构无效。")
    rows = report["scenes"]
    require(len(rows) == len(scenes), "估时报告镜头数量不一致。")
    total = 0
    for scene, row in zip(scenes, rows):
        require(isinstance(row, dict) and row.get("scene_id") == scene.beat.id, "估时报告镜头顺序或编号不一致。")
        spoken, reading = text_seconds(scene.beat)
        expected = {"planned_seconds": scene.planned_seconds,
                    "minimum_visual_seconds": scene.minimum_visual_seconds,
                    "spoken_seconds": spoken, "reading_seconds": reading,
                    "estimated_seconds": max(scene.planned_seconds, scene.minimum_visual_seconds, spoken, reading)}
        require(all(type(row.get(key)) is int and row[key] == value
                    for key, value in expected.items()), "估时明细与当前镜头不一致。")
        total += row["estimated_seconds"]
    require(type(report.get("total_seconds")) is int and report["total_seconds"] == total
            and type(report.get("over_seconds")) is int
            and report["over_seconds"] == max(0, total - target)
            and report["passed"] == (total <= target), "估时汇总与逐镜明细不一致。")


def materials_contract(items, catalog, subject, material_id="") -> None:
    from .tools import normalized
    require(isinstance(items, tuple) and all(isinstance(item, Material) for item in items), "检索结果类型不合法。")
    require(len({item.id for item in items}) == len(items), "检索结果含重复素材 ID。")
    for item in items:
        require(item in catalog and normalized(subject) in {
            normalized(alias) for alias in (item.subject, *item.aliases)
        } and (not material_id or item.id == material_id), "检索结果不属于请求主体、指定素材或当前素材库。")


def plans_contract(plans, brief, materials) -> None:
    from .schema import CREATIVE_FIELDS, CreativePlan
    require(isinstance(plans, tuple) and 1 <= len(plans) <= 2
            and all(isinstance(plan, CreativePlan) for plan in plans), "创意阶段必须返回一到两个方案。")
    require(all(isinstance(plan.id, str) for plan in plans), "方案 ID 必须为字符串。")
    require(len({plan.id for plan in plans}) == len(plans), "创意方案 ID 不能重复。")
    for plan in plans:
        for key in ('id', 'approach', 'audience_insight', 'protagonist_goal', 'obstacle',
                    'product_role', 'payoff', 'cta_reason', 'presentation', 'focus', *CREATIVE_FIELDS):
            require(isinstance(getattr(plan, key), str), "创意方案字段必须为字符串。")
        require(all(getattr(plan, key).strip() for key in ('id', 'protagonist_goal', 'obstacle', 'opening', 'resolution')),
                "创意方案缺少目标、阻碍、开场或兑现。")
        require(isinstance(plan.material_ids, tuple) and all(isinstance(item, str) for item in plan.material_ids),
                "创意方案素材引用格式无效。")
        require(isinstance(plan.assumptions, tuple) and bool(plan.assumptions)
                and all(isinstance(item, str) for item in plan.assumptions), "创意设定须显式标注假设。")
        require(isinstance(plan.field_origins, tuple) and all(isinstance(pair, tuple) and len(pair) == 2
                and pair[0] in CREATIVE_FIELDS and pair[1] in ('user_locked', 'mock_proposal', 'llm_proposal')
                for pair in plan.field_origins), "创意字段来源格式无效。")
        require({pair[0] for pair in plan.field_origins} == set(CREATIVE_FIELDS), "创意字段来源不完整。")
        require((brief.fictional and not plan.material_ids) or (not brief.fictional and len(plan.material_ids) == 1),
                "事实方案须绑定一项主证据，虚构方案不得冒用事实素材。")
        if plan.material_ids:
            item = next((item for item in materials if item.id == plan.material_ids[0]), None)
            require(item is not None and (not brief.proof_id or item.id == brief.proof_id), "方案引用的素材未获授权。")
            from .tools import normalized
            require(normalized(brief.visible_result) in normalized(item.visual), "方案不能兑现所需结果画面。")
        for key in CREATIVE_FIELDS:
            if brief.creative_policy == 'locked' and getattr(brief, key):
                require(getattr(plan, key) == getattr(brief, key), "方案更改了用户锁定的创意内容。")


def locked_creative_contract(brief, draft) -> None:
    if brief.creative_policy != 'locked':
        return
    by_purpose = {beat.purpose: beat for beat in draft.beats}
    mapping = {'opening': ('hook', 'action'), 'setting': ('hook', 'action'),
               'hook_line': ('hook', 'voiceover'), 'turn': ('turn', 'action'),
               'turn_line': ('turn', 'voiceover'), 'resolution': ('resolution', 'action')}
    for key, (purpose, field) in mapping.items():
        requested = getattr(brief, key)
        if not requested:
            continue
        beat = by_purpose.get(purpose)
        require(beat is not None and requested.rstrip('。') in getattr(beat, field),
                f"脚本未保留用户锁定字段 {key}。")


def creative_report_contract(report, draft) -> None:
    report_contract(report)
    beats = {beat.id: beat for beat in draft.beats}
    codes = {'GENERIC_HOOK': 'voiceover', 'MISSING_MOTIVATION': 'action',
             'UNRESOLVED_PAYOFF': 'action', 'REDUNDANT_COPY': 'voiceover'}
    semantic_codes = {'CAUSAL_GAP', 'OFF_TOPIC', 'PACING', 'PRODUCT_FIT'}
    targets = set()
    for issue in report['issues']:
        beat = beats.get(issue['scene_id'])
        require(beat is not None and ((issue['code'] in codes and issue['field'] == codes[issue['code']])
                or (issue['code'] in semantic_codes and issue['field'] in {'action','voiceover','subtitle'})),
                "创作评审必须定位到有效镜头与可修订字段。")
        require(isinstance(issue.get('evidence'), str) and issue['evidence'] == getattr(beat, issue['field'])
                and isinstance(issue.get('revision_goal'), str) and bool(issue['revision_goal'].strip()),
                "创作评审缺少可核对原文或具体修改目标。")
        require(isinstance(issue.get('preserve'), list) and bool(issue['preserve'])
                and all(isinstance(item, str) for item in issue['preserve']), "创作评审缺少保留约束。")
        target = issue['scene_id'], issue['field']
        require(target not in targets, "同一字段应合并为一次修订请求。")
        targets.add(target)


def creative_revision_contract(brief, before, after, issues) -> None:
    from .creative import creative_lock
    draft_contract(after)
    require(before.title == after.title and len(before.beats) == len(after.beats), "创作修订不得更换标题或增删镜头。")
    targets = {(issue['scene_id'], issue['field']) for issue in issues}
    for old, new in zip(before.beats, after.beats):
        require((old.id, old.purpose, old.material_id) == (new.id, new.purpose, new.material_id),
                "创作修订不得更换镜头编号、用途或引用。")
        for field in ('action', 'voiceover', 'subtitle'):
            if getattr(old, field) != getattr(new, field):
                require((old.id, field) in targets and not creative_lock(brief, old, field),
                        "创作修订越出目标字段或修改了锁定事实/入口。")
    locked_creative_contract(brief, after)


def grounding_revision_contract(brief,before,after,issues):
    # A generated title may be revised only if the audit explicitly flagged it.
    from dataclasses import replace
    if before.title != after.title:
        require(any(i['scene_id']=='title' and i['field']=='title' for i in issues), '未定位标题问题，不得改标题。')
    creative_revision_contract(brief,before,replace(after,title=before.title),issues)
