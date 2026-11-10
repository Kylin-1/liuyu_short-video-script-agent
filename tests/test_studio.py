import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.main import DATA, load_json, load_materials, load_rules
from src.models import MockModels
from src.schema import Beat, Decision, InputError, Scene
from src.studio import Studio
from src.tools import LocalTools, read_units

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "inputs"


def make_studio(models=None, max_steps=14, fault="", fault_times=0):
    tools = LocalTools(load_materials(DATA / "materials.json"),
                       load_rules(DATA / "brand_rules.json"), fault, fault_times)
    return Studio(models or MockModels(), tools, max_steps, creative_mode="legacy")


def run_case(name, **kwargs):
    return make_studio(**kwargs).run(load_json(FIXTURES / f"{name}.json"))


def actions(result):
    return [entry["action"] for entry in result["trace"]]


def tool_results(result, name):
    return [call["result"] for entry in result["trace"]
            for call in entry["calls"] if call["tool"] == name]


class StudioTests(unittest.TestCase):
    def test_normal_has_zh_output_and_timing_reconciles(self):
        result = run_case("normal")
        script = result["script"]
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["model_mode"], "mock")
        self.assertEqual(script["language"], "zh-CN")
        self.assertIn("随行杯", script["title"])
        self.assertEqual(script["material_ids"], ["P01"])
        self.assertEqual(sum(scene["estimated_seconds"] for scene in script["scenes"]),
                         script["estimated_seconds"])
        self.assertEqual(actions(result), ["FIND_MATERIAL", "WRITE", "DIRECT",
                                           "CHECK", "REVIEW", "DELIVER"])
        self.assertEqual(result["trace"][3]["next_action"], "REVIEW")

    def test_same_first_draft_revises_for_tighter_limit(self):
        normal = run_case("normal")
        shorter = run_case("shorter")
        self.assertEqual(shorter["status"], "COMPLETED")
        self.assertEqual(shorter["revision_count"], 1)
        self.assertEqual(shorter["script_version"], 2)
        estimates = tool_results(shorter, "estimate_duration")
        baseline = tool_results(normal, "estimate_duration")[0]
        self.assertEqual(baseline["scenes"], estimates[0]["scenes"])
        self.assertEqual(baseline["total_seconds"], estimates[0]["total_seconds"])
        self.assertGreater(estimates[0]["total_seconds"], 15)
        self.assertLessEqual(estimates[-1]["total_seconds"], 15)
        self.assertEqual(shorter["trace"][3]["next_action"], "REVISE_COPY")
        self.assertTrue(shorter["script"]["scenes"][0]["voiceover"].endswith("？"))
        self.assertEqual(shorter["script"]["scenes"][1]["voiceover"], "杯盖带滑动锁扣。")
        self.assertEqual(shorter["script"]["scenes"][1]["estimated_seconds"], 8)

    def test_impossible_duration_does_not_publish_draft(self):
        result = run_case("impossible")
        self.assertEqual(result["status"], "DURATION_UNMET")
        self.assertIsNone(result["script"])
        self.assertNotIn("DELIVER", actions(result))

    def test_missing_details_prompt_before_tools(self):
        result = run_case("missing_input")
        self.assertEqual(result["status"], "NEEDS_INPUT")
        self.assertEqual(result["requested_fields"], ["受众"])
        self.assertEqual(actions(result), ["ASK"])

    def test_absent_material_triggers_refinement_then_request(self):
        result = run_case("no_material")
        self.assertEqual(result["status"], "MATERIAL_REQUIRED")
        self.assertEqual(actions(result), ["FIND_MATERIAL", "FIND_MATERIAL", "ASK"])
        self.assertEqual([step["args"]["query"] for step in result["trace"][:2]], ["背包", ""])
        self.assertIsNone(result["script"])

    def test_refined_query_matches_only_original_subject(self):
        result = run_case("search_recovered")
        hits = tool_results(result, "search_material")
        self.assertEqual(hits[0], [])
        self.assertEqual([item["id"] for item in hits[1]], ["P01"])

    def test_persistent_tool_failure_has_one_retry(self):
        result = run_case("tool_failure", fault="search_material", fault_times=2)
        self.assertEqual(result["status"], "TOOL_FAILED")
        self.assertEqual(actions(result), ["FIND_MATERIAL", "FIND_MATERIAL", "STOP"])
        self.assertTrue(result["trace"][1]["args"]["retry"])
        self.assertEqual([outcome["status"] for outcome in tool_results(result, "search_material")],
                         ["error", "error"])

    def test_transient_quality_failure_recovers(self):
        result = run_case("normal", fault="check_brand", fault_times=1)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(actions(result).count("CHECK"), 2)
        self.assertEqual(tool_results(result, "check_brand")[0]["status"], "error")
        self.assertTrue(tool_results(result, "check_brand")[1]["passed"])

    def test_store_coupon_and_fictional_campaign_use_same_runtime(self):
        tutorial, fiction = run_case("tutorial"), run_case("fiction")
        self.assertEqual([tutorial["status"], fiction["status"]], ["COMPLETED", "NEEDS_REVIEW"])
        self.assertEqual(tutorial["script"]["material_ids"], ["T01"])
        self.assertIsNone(fiction["script"])
        self.assertEqual(tool_results(fiction, "search_material"), [])
        self.assertTrue(fiction["checks"]["grounding"]["issues"])

    def test_user_topic_is_not_an_authorized_product_claim(self):
        result = run_case("brand_blocked")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertNotIn("全网第一", result["script"]["title"])
        self.assertTrue(result["checks"]["grounding"]["passed"])

    def test_reviewer_rejects_unbacked_visual_even_with_valid_id(self):
        class WrongVisual(MockModels):
            def director(self, brief, draft, compact):
                setup, payoff, close = super().director(brief, draft, compact)
                return setup, replace(payoff, beat=replace(payoff.beat,
                                      action="倒置水杯一整天，纸巾保持干燥")), close

        result = run_case("normal", models=WrongVisual())
        self.assertEqual(result["status"], "MODEL_FAILED")
        self.assertIn("导演不能替换", result["detail"])

    def test_stale_review_cannot_authorize_new_version(self):
        class OutOfOrder(MockModels):
            def producer(self, state):
                if state.last.get("action") == "REVIEW":
                    return Decision("DIRECT", "测试重新排镜")
                if state.version == 2:
                    return Decision("DELIVER", "测试使用旧检查")
                return super().producer(state)

        result = run_case("normal", models=OutOfOrder())
        self.assertEqual(result["status"], "INVALID_ACTION")
        self.assertEqual(result["script_version"], 2)
        self.assertIsNone(result["script"])

    def test_step_cap(self):
        result = run_case("normal", max_steps=1)
        self.assertEqual(result["status"], "STEP_LIMIT")
        self.assertEqual(len(result["trace"]), 1)
        self.assertEqual(result["trace"][0]["next_action"], "STEP_LIMIT")
        self.assertIsNone(result["script"])

    def test_invalid_duration_rejects_bool(self):
        raw = load_json(FIXTURES / "normal.json")
        with self.assertRaises(InputError):
            make_studio().run({**raw, "target_seconds": True})

    def test_subtitle_only_and_repeated_subtitle_timing(self):
        text = "周末到店请出示领券码"
        scenes = (Scene(Beat("S01", "setup", "门店海报特写", subtitle=text), 1, 1),
                  Scene(Beat("S02", "payoff", "门店海报特写", voiceover=text, subtitle=text), 1, 1))
        estimate = make_studio().tools.estimate_duration(scenes, 8)
        self.assertEqual(estimate["scenes"][0]["reading_seconds"], 2)
        self.assertEqual(estimate["scenes"][1]["reading_seconds"], 0)
        self.assertEqual(estimate["total_seconds"], 5)
        self.assertGreater(read_units("立减80%"), read_units("立减"))

    def test_cli_writes_parseable_output_and_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.json"
            args = [sys.executable, "-X", "utf8", "-m", "src.main", "--creative-mode", "legacy",
                    str(FIXTURES / "normal.json"), "--json", "--trace", str(trace)]
            proc = subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8", capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["status"], "COMPLETED")
            self.assertEqual(load_json(trace)["steps"][-1]["action"], "DELIVER")


if __name__ == "__main__":
    unittest.main()
