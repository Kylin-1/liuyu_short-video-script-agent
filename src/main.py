"""CLI for the offline short-video studio."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .intent import GOALS
from .intake import normalize, split_text
from .models import MockModels
from .remote import from_environment
from .schema import InputError, Material
from .studio import DEFAULT_STEPS, DEFAULT_TOOL_CALLS, LABELS, Studio
from .tools import TOOL_NAMES, LocalTools

DATA = Path(__file__).resolve().parents[1] / "data"


def atomic_json(path: Path, value: dict) -> None:
    """Keep the previous trace intact if serialization or writing fails."""
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".trace-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_request(path: Path):
    if path.suffix.lower() in {".txt", ".md"}:
        return {"brief_text": "", **split_text(path.read_text(encoding="utf-8-sig"))}
    return load_json(path)


def load_materials(path: Path, record_source: bool = False) -> tuple[Material, ...]:
    rows = load_json(path)
    if not isinstance(rows, list):
        raise InputError("素材库必须是 JSON 数组。")
    materials = []
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or any(
            not isinstance(row.get(field), str) or not row[field].strip()
            for field in ("id", "subject", "fact", "visual")
        ):
            raise InputError("素材必须填写 id、subject、fact 和 visual。")
        collections = {}
        for key in ("aliases", "tags"):
            values = row.get(key, [])
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise InputError(f"素材的 {key} 必须是字符串数组。")
            collections[key] = tuple(value.strip() for value in values if value.strip())
        source, operation = row.get("source", ""), row.get("operation", "")
        if not isinstance(source, str) or not isinstance(operation, str):
            raise InputError("素材的 source 和 operation 必须是字符串。")
        if record_source and not source.strip():
            source = f"{path.name}#{row['id'].strip()}"
        material = Material(**{key: row[key].strip() for key in ("id", "subject", "fact", "visual")},
                            **collections, source=source.strip(), operation=operation.strip())
        if material.id in ids:
            raise InputError("素材 ID 重复。")
        ids.add(material.id)
        materials.append(material)
    return tuple(materials)


def load_rule_config(path: Path) -> dict:
    raw = load_json(path)
    if not isinstance(raw, dict) or set(raw) - {"banned_terms", "required_terms"}:
        raise InputError("品牌规则仅支持 banned_terms 和 required_terms，未知规则不能被静默忽略。")
    result = {}
    for key in ("banned_terms", "required_terms"):
        values = raw.get(key, [] if key == "required_terms" else None)
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
            raise InputError(f"品牌规则 {key} 须为非空词语组成的数组。")
        result[key] = tuple(dict.fromkeys(value.strip() for value in values))
    from .tools import normalized
    if any(normalized(ban) in normalized(term) for ban in result['banned_terms'] for term in result['required_terms']):
        raise InputError("品牌必说项包含禁用词，请先解决规则冲突。")
    return result


def load_rules(path: Path) -> tuple[str, ...]:
    """Compatibility helper for callers that explicitly only request banned terms."""
    return load_rule_config(path)["banned_terms"]


def markdown(result: dict) -> str:
    mode = ("模型决策与创作" if result.get("creative_model_mode")=="llm" else "模型决策 · 本地创作模板") if result["model_mode"] == "llm" else "离线 Mock"
    lines = [f"**任务状态** {result['status_text']} · {mode}", "", result["detail"]]
    checks = result.get("checks", {})
    for phase in ("rules_and_claims", "grounding", "review", "creative_review"):
        for issue in (checks.get(phase) or {}).get("issues", []):
            location = " ".join(value for value in (issue.get("scene_id"), issue.get("field")) if value)
            lines.append(f"- {location} · {issue['code']} {issue.get('revision_goal', issue.get('value', ''))}".rstrip())
            if issue.get("evidence"):
                lines.append(f"  原句：{issue['evidence']}")
    if result["requested_fields"]:
        lines.extend(["", "待补充项目：" + "、".join(result["requested_fields"])])
    if result.get("intake", {}).get("questions"):
        lines.extend(["", *[f"- {item}" for item in result["intake"]["questions"]]])
    script = result["script"]
    if not script:
        return "\n".join(lines)

    def cell(value: str) -> str:
        return value.replace("|", r"\|").replace("\r", " ").replace("\n", " ")

    lines.extend(["", f"# {script['title']}", "",
                  f"受众 {script['audience']} · 平台 {script['platform']} · 风格 {script['style']}", "",
                  f"画幅 {script['aspect_ratio']} · 目标 {script['target_seconds']} 秒"
                  f" · 预计总长 {script['estimated_seconds']} 秒", ""])
    chosen = next((plan for plan in result.get("creative", {}).get("plans", [])
                   if plan["id"] == result["creative"]["selected_plan_id"]), None)
    if chosen:
        lines.extend([f"**创意方向** {chosen['approach']} · {chosen['protagonist_goal']}", "",
                      f"人物阻碍：{chosen['obstacle']}。", "",
                      "创作设定为虚构情境，商品事实以逐镜引用为准。", ""])
    if script["production"]:
        goal = GOALS.get(script["goal"], "")
        objective = " · ".join(value for value in (goal, script["objective"]) if value)
        if objective:
            lines.extend([f"**视频目标** {objective}", ""])
        lines.extend([
                      "| 镜头 · 时间 | 画面与动作 | 旁白 | 屏幕文字 | 素材出处 |",
                      "| --- | --- | --- | --- | --- |"])
    else:
        lines.extend(["| 镜头 | 计划 / 估算 | 画面 | 旁白 | 字幕 | 素材 | 衔接 |",
                      "| --- | --- | --- | --- | --- | --- | --- |"])
    for scene in script["scenes"]:
        refs = "、".join(scene["material_ids"])
        if script["production"]:
            fields = [f"{scene['id']} · {scene['start_seconds']}–{scene['end_seconds']} 秒",
                      scene["visual"], scene["voiceover"], scene["subtitle"],
                      f"{refs} · {scene['source']}" if scene["source"] else refs]
        else:
            fields = [scene["id"], f"{scene['planned_seconds']} / {scene['estimated_seconds']} 秒",
                      scene["visual"], scene["voiceover"], scene["subtitle"], refs, scene["continuity"]]
        lines.append("| " + " | ".join(cell(value) if value else "—" for value in fields) + " |")
    if script["production"]:
        lines.extend(["", "## 拍摄与剪辑", ""])
        for scene in script["scenes"]:
            lines.append(f"- **{scene['id']}**　{scene['framing']}。{scene['sound']}。"
                         f"{scene['transition']}。{scene['continuity']}。")
    lines.extend(["", "## 本次检查", "",
                  f"- 估时 {script['estimated_seconds']} / {script['target_seconds']} 秒。",
                  "- 当前版本通过规则、来源及流程检查，逐镜依据见素材列。"])
    evidence = {item["material_id"]: item for scene in script["scenes"] for item in scene["evidence"]}
    for item in evidence.values():
        lines.append(f"- `{item['material_id']}` 事实原文「{item['fact']}」")
    lines.extend(["", "## 风险", "", *[f"- {risk}" for risk in script["risks"]]])
    return "\n".join(lines)


def unfinished(status: str, detail: str, requested_fields: list[str] | None = None) -> dict:
    return {"model_mode": "mock", "status": status, "status_text": LABELS[status],
            "detail": detail, "requested_fields": requested_fields or [], "script": None,
            "script_version": 0, "revision_count": 0, "trace": []}


def run_request(args) -> dict:
    raw = load_request(args.input)
    config = load_rule_config(args.rules)
    banned, required = config["banned_terms"], config["required_terms"]
    report = None
    if isinstance(raw, dict) and {"brief_text", "material_notes", "brand_notes", "confirmed"} & raw.keys():
        catalog = load_materials(args.materials, record_source=True) if args.materials else ()
        intake = normalize(raw, banned, catalog, source_file=args.input.name)
        report = intake.report()
        if intake.questions:
            result = unfinished("NEEDS_INPUT", "请先确认制作简报。", intake.missing)
            return {**result, "intake": report}
        raw = intake.fields
        materials = intake.materials
        banned += tuple(rule["term"] for rule in intake.rules if rule["kind"] == "banned")
        required += tuple(rule["term"] for rule in intake.rules if rule["kind"] == "required")
    elif args.brief_only:
        raise InputError("--brief-only 请用于文本需求或包含 brief_text 的 JSON 请求。")
    else:
        materials = load_materials(args.materials or DATA / "materials.json", record_source=True)
    from .tools import normalized
    if any(normalized(ban) in normalized(term) for ban in banned for term in required):
        raise InputError("合并后的品牌必说项包含禁用词，请先解决规则冲突。")
    if args.brief_only:
        return {"status": "READY", "intake": report, "model_mode": "mock", "trace": []}
    tools = LocalTools(materials, banned, args.fail_tool or "", args.fail_times, required=required)
    if args.model=="llm" and args.creative_mode!="planned":
        raise InputError("真实多角色模型请使用 planned；legacy 只用于离线对照。")
    models = from_environment() if args.model == "llm" else MockModels()
    result = Studio(models, tools, args.max_steps, args.max_tool_calls, args.creative_mode).run(raw)
    return {**result, "intake": report} if report is not None else result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全品类中文短视频脚本工作室")
    parser.add_argument("input", type=Path, help="原始需求 .txt/.md 或 JSON")
    parser.add_argument("--creative-mode", choices=("planned", "legacy"), default="planned",
                        help="planned 创意评审闭环；legacy 保留旧模板作对照")
    parser.add_argument("--model", choices=("mock", "llm"), default="mock")
    parser.add_argument("--materials", type=Path, help="显式提供本次素材 JSON 附件")
    parser.add_argument("--rules", type=Path, default=DATA / "brand_rules.json")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--max-tool-calls", type=int, default=DEFAULT_TOOL_CALLS)
    parser.add_argument("--fail-tool", choices=TOOL_NAMES)
    parser.add_argument("--fail-times", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="输出结构化结果")
    parser.add_argument("--trace", type=Path, help="将完整执行记录写入 JSON")
    parser.add_argument("--brief-only", action="store_true", help="只输出整理后的 Brief，不生成脚本")
    args = parser.parse_args(argv)
    if args.max_steps <= 0 or args.max_tool_calls <= 0 or args.fail_times < 0:
        parser.error("步骤与工具调用上限必须为正数，模拟失败次数须为非负数。")
    if args.trace:
        protected = [args.input, args.materials or DATA / "materials.json", args.rules]
        if any(args.trace.resolve() == path.resolve() or (
            args.trace.exists() and path.exists() and args.trace.samefile(path)
        ) for path in protected):
            parser.error("运行记录路径不能覆盖需求、素材或品牌规则输入。")
    try:
        result = run_request(args)
    except (InputError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = {**unfinished("INVALID_INPUT", str(exc)), "model_mode": args.model}

    if args.trace:
        try:
            trace = {"model_mode": result["model_mode"], "status": result["status"],
                     "llm_decisions": result.get("llm_decisions", 0), "checks": result.get("checks"),
                     "audit": result.get("audit"), "creative_mode": result.get("creative_mode"),
                     "decision_model": result.get("decision_model"), "creative_model_mode": result.get("creative_model_mode"),
                     "creative": result.get("creative"),
                     "steps": result["trace"]}
            if "intake" in result:
                trace["intake"] = result["intake"]
            atomic_json(args.trace, trace)
        except OSError as exc:
            print(f"无法写入运行记录：{exc}", file=sys.stderr)
            return 2
    if args.json or args.brief_only:
        output = {key: value for key, value in result.items() if key != "trace"}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(markdown(result))
    return 0 if result["status"] in {"COMPLETED", "READY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
