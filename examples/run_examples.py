"""Regenerate the CLI outputs, traces and test log under examples/."""
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
RUNS = EXAMPLES / "runs"
CASES = {
    "normal": ("COMPLETED", []),
    "shorter": ("COMPLETED", []),
    "impossible": ("DURATION_UNMET", []),
    "missing_input": ("NEEDS_INPUT", []),
    "no_material": ("MATERIAL_REQUIRED", []),
    "tool_failure": ("TOOL_FAILED", ["--fail-tool", "search_material", "--fail-times", "2"]),
    "tutorial": ("COMPLETED", []),
    "campaign_store": ("COMPLETED", []),
    "campaign_event": ("COMPLETED", []),
    "fiction": ("NEEDS_REVIEW", []),
    "brand_blocked": ("COMPLETED", []),
    "search_recovered": ("COMPLETED", []),
    "raw_brief": ("NEEDS_REVIEW", []),
    "raw_conflict": ("NEEDS_INPUT", []),
    "raw_rule_blocked": ("QUALITY_FAILED", []),
    "raw_production": ("NEEDS_REVIEW", []),
    "raw_production_short": ("NEEDS_REVIEW", []),
    "raw_tutorial": ("NEEDS_REVIEW", []),
    "raw_proof_gap": ("MATERIAL_REQUIRED", []),
    "raw_intent_demo": ("COMPLETED", []),
    "raw_intent_story": ("COMPLETED", []),
    "raw_intent_store": ("COMPLETED", []),
    "raw_reference_p01": ("NEEDS_REVIEW", []),
    "raw_rule_repaired": ("COMPLETED", []),
    "raw_disclosure_repaired": ("COMPLETED", []),
    "tool_budget": ("TOOL_LIMIT", ["--max-tool-calls", "2"]),
    "raw_unbacked_claim": ("QUALITY_FAILED", []),
    "same_input_empty_catalog": ("MATERIAL_REQUIRED", ["--materials", "examples/inputs/empty_catalog.json"]),
}


# New default flow, separately labeled from the frozen legacy regression fixtures.
CREATIVE_CASES = {
    "p01_duration": ("campaign_p01.txt", "COMPLETED", []),
    "attack_weight_locked": ("attack_weight_locked.txt", "NEEDS_REVIEW", []),
    "attack_weight_reference": ("attack_weight_reference.txt", "COMPLETED", []),
    "attack_leak": ("attack_leak.txt", "NEEDS_REVIEW", []),
    "attack_moon": ("attack_moon.txt", "NEEDS_REVIEW", []),
    "valid_custom_deferred": ("valid_custom_deferred.txt", "NEEDS_REVIEW", []),
    "creative_sales": ("raw_intent_story.txt", "COMPLETED", []),
    "creative_demo": ("raw_intent_demo.txt", "COMPLETED", []),
    "creative_store": ("campaign_store.txt", "COMPLETED", []),
    "creative_event": ("campaign_event.txt", "COMPLETED", []),
    "creative_reference": ("raw_creative_reference.txt", "COMPLETED", []),
    "creative_locked": ("raw_creative_locked.txt", "QUALITY_FAILED", []),
    "creative_missing": ("missing_input.json", "NEEDS_INPUT", []),
    "creative_no_material": ("no_material.json", "MATERIAL_REQUIRED", []),
    "creative_tool_failure": ("tool_failure.json", "TOOL_FAILED", ["--fail-tool", "search_material", "--fail-times", "2"]),
    "creative_short": ("campaign_short.txt", "COMPLETED", []),
    "creative_impossible": ("impossible.json", "DURATION_UNMET", []),
}


def run(args):
    return subprocess.run([sys.executable, "-X", "utf8", *args], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHON_COLORS": "0"})


def save(path, content):
    path.write_text(content, encoding="utf-8")


def main():
    RUNS.mkdir(exist_ok=True)
    # Remove only generated previews so an obsolete completed script cannot
    # survive when its case now correctly defers. Keep inputs untouched.
    for pattern in ('*.output.md','*.normalized.json'):
        for path in RUNS.glob(pattern):
            path.unlink()
    summaries = []
    for name, (status, flags) in CASES.items():
        suffix = "txt" if (EXAMPLES / "inputs" / f"{name}.txt").exists() else "json"
        source_name = "normal" if name in {"same_input_empty_catalog", "tool_budget"} else name
        cli = ["-m", "src.main", f"examples/inputs/{source_name}.{suffix}", "--model", "mock", "--creative-mode", "legacy", *flags]
        trace_path = RUNS / f"{name}.trace.json"
        process = run([*cli, "--json", "--trace", str(trace_path)])
        result = json.loads(process.stdout)
        expected_code = 0 if status == "COMPLETED" else 2
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        if (result["status"], trace["status"], trace["model_mode"], process.returncode) != (
                status, status, "mock", expected_code):
            raise RuntimeError(f"{name} expected {status}, got {result['status']}: {result.get('detail')}")
        save(RUNS / f"{name}.output.json", process.stdout)
        summaries.append({'case': name, 'status': result['status'], 'mode': result.get('creative_mode', 'intake'),
                          'input': cli[2], 'seconds': (result.get('script') or {}).get('estimated_seconds'),
                          'steps': result.get('audit', {}).get('steps', 0),
                          'llm_decisions': result.get('llm_decisions', 0)})
        print(f"{name}: {status}")

    previews = ("normal", "raw_intent_demo", "raw_intent_story", "raw_intent_store",
                "campaign_store", "campaign_event", "raw_disclosure_repaired")
    for name in previews:
        suffix = "txt" if (EXAMPLES / "inputs" / f"{name}.txt").exists() else "json"
        source = f"examples/inputs/{name}.{suffix}"
        preview = run(["-m", "src.main", source, "--creative-mode", "legacy"])
        preview.check_returncode()
        save(RUNS / f"{name}.output.md", preview.stdout)
        if suffix == "txt":
            brief = run(["-m", "src.main", source, "--brief-only"])
            brief.check_returncode()
            save(RUNS / f"{name}.normalized.json", brief.stdout)
    for name, (filename, status, flags) in CREATIVE_CASES.items():
        cli = ["-m", "src.main", f"examples/inputs/{filename}", "--creative-mode", "planned", *flags]
        process = run([*cli, "--json", "--trace", str(RUNS / f"{name}.trace.json")])
        result = json.loads(process.stdout)
        if (result["status"], process.returncode) != (status, 0 if status == "COMPLETED" else 2):
            raise RuntimeError(f"{name}: {result['status']} {result.get('detail')}")
        save(RUNS / f"{name}.output.json", process.stdout)
        if name in {"creative_sales", "creative_demo", "creative_store", "creative_event", "creative_reference", "p01_duration", "attack_weight_reference"}:
            preview = run(cli)
            preview.check_returncode()
            save(RUNS / f"{name}.output.md", preview.stdout)
        summaries.append({'case': name, 'status': result['status'], 'mode': result.get('creative_mode', 'intake'),
                          'input': cli[2], 'seconds': (result.get('script') or {}).get('estimated_seconds'),
                          'steps': result.get('audit', {}).get('steps', 0),
                          'llm_decisions': result.get('llm_decisions', 0)})
        print(f"{name}: {status}")
    save(EXAMPLES / 'case-results.json', json.dumps({'evidence_mode':'offline_mock', 'cases':summaries}, ensure_ascii=False, indent=2)+'\n')
    index = ['# 本版运行结果', '', '所有条目由本版 CLI 重新运行；模型为 Mock。脚本只在 COMPLETED 时存在。', '',
             '| 用例 | 状态 | 秒数 | 原始输入 | 实际输出 | Trace |', '| --- | --- | --- | --- | --- | --- |']
    for row in summaries:
        name=row['case']
        index.append(f"| {name} | {row['status']} | {row['seconds'] or '—'} | [输入]({row['input'].replace('examples/', '')}) | [结果](runs/{name}.output.json) | [记录](runs/{name}.trace.json) |")
    save(EXAMPLES / 'INDEX.md', '\n'.join(index)+'\n')
    comparison = run(["examples/evaluate_creative.py"])
    comparison.check_returncode()
    protocol = run(["examples/run_protocol_examples.py"])
    protocol.check_returncode()
    tests = run(["-m", "unittest", "discover", "-s", "tests", "-v"])
    save(EXAMPLES / "test-results.txt", tests.stdout + tests.stderr)
    tests.check_returncode()


if __name__ == "__main__":
    main()
