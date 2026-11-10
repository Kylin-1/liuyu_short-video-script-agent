import json
import subprocess
import sys
import unittest
from pathlib import Path

from src.intake import normalize, split_text

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "examples" / "inputs" / "raw_intent_demo.txt"


class IntentTests(unittest.TestCase):
    def run_case(self, name):
        run = subprocess.run([sys.executable, "-X", "utf8", "-m", "src.main", "--creative-mode", "legacy",
                              f"examples/inputs/{name}.txt", "--json"],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
        result = json.loads(run.stdout)
        self.assertEqual(result["status"], "COMPLETED")
        return result

    def test_same_purchase_goal_changes_shots_when_format_changes(self):
        demo = self.run_case("raw_intent_demo")["script"]
        story = self.run_case("raw_intent_story")["script"]
        self.assertEqual(demo["goal"], story["goal"])
        self.assertEqual(demo["conversion"], story["conversion"])
        self.assertEqual(demo["scenes"][-1]["subtitle"], story["scenes"][-1]["subtitle"])
        self.assertNotIn("turn", [scene["purpose"] for scene in demo["scenes"]])
        self.assertIn("turn", [scene["purpose"] for scene in story["scenes"]])
        self.assertEqual(story["scenes"][-1]["purpose"], "resolution")
        self.assertEqual(demo["material_ids"], story["material_ids"])

    def test_same_story_changes_opening_and_destination_when_goal_changes(self):
        sale = self.run_case("raw_intent_story")["script"]
        leads = self.run_case("raw_intent_store")["script"]
        self.assertEqual(sale["format"], leads["format"])
        self.assertNotEqual(sale["scenes"][0]["visual"], leads["scenes"][0]["visual"])
        self.assertEqual(leads["scenes"][-1]["subtitle"], "到门店小程序领券")
        self.assertIn("先领券再进去", leads["scenes"][-1]["visual"])
        self.assertEqual(sale["material_ids"], leads["material_ids"])

    def test_report_preserves_goal_source_and_preference(self):
        result = self.run_case("raw_intent_demo")
        brief = result["intake"]["brief"]
        goal = next(evidence for evidence in brief["field_evidence"] if evidence["field_path"] == "goal.primary")
        self.assertEqual(goal["source"]["source_file"], "raw_intent_demo.txt")
        self.assertEqual(goal["source"]["text"], "主目标：促进购买")
        self.assertEqual(brief["creative"]["format_policy"], "locked")
        self.assertEqual(brief["soft_preferences"], [{"field": "style", "value": "快节奏、生活化"}])

    def test_missing_destination_and_wrong_action_stop_before_generation(self):
        source = INPUT.read_text(encoding="utf-8")
        no_destination = normalize(split_text(source.replace("；承接入口：视频下方商品卡", "")))
        self.assertIn("承接入口", no_destination.missing)
        wrong_action = normalize(split_text(source.replace("转化动作：点商品卡", "转化动作：领券")))
        self.assertTrue(any("转化动作与主目标不匹配" in message for message in wrong_action.questions))

    def test_goal_conflict_keeps_evidence_and_allows_field_confirmation(self):
        source = INPUT.read_text(encoding="utf-8")
        raw = split_text(source.replace("主目标：促进购买", "主目标：促进购买；主目标：到店引流"))
        conflict = normalize(raw)
        self.assertEqual({item["value"] for item in conflict.conflicts["goal"]}, {"purchase", "store_visit"})
        repaired = normalize({**raw, "confirmed": {"goal": "purchase"}})
        self.assertFalse(repaired.questions)
        self.assertEqual(repaired.sources["goal"]["selected"]["kind"], "confirmed")

    def test_semantic_candidates_are_batched_and_need_a_real_quote(self):
        calls = []

        def extractor(text):
            calls.append(text)
            return [("goal", "purchase", "本条用于带货"), ("style", "热血", "不存在的原文")]

        intake = normalize({"brief_text": "本条用于带货\n请交一条成片", "brand_notes": "无额外品牌规则"},
                           extract_intent=extractor)
        self.assertEqual(calls, ["本条用于带货\n请交一条成片"])
        self.assertEqual(intake.fields["goal"], "purchase")
        self.assertNotIn("style", intake.fields)
        self.assertIn("承接入口", intake.missing)

    def test_unlocked_format_is_proposed_but_missing_style_needs_input(self):
        source = INPUT.read_text(encoding="utf-8")
        intake = normalize(split_text(source.replace("；内容形式：功能演示；风格：快节奏、生活化", "")))
        self.assertIn("请补充风格。", intake.questions)
        self.assertEqual(intake.fields["format_policy"], "propose")
        complete = normalize(split_text(source.replace("；内容形式：功能演示", "")))
        self.assertFalse(complete.questions)
        self.assertEqual(complete.sources["format"]["selected"]["kind"], "proposal")

    def test_natural_intent_does_not_confuse_goal_and_preferred_form(self):
        raw = {"brief_text": "用小剧情，把人引到门店小程序领券。\n最好拍成剧情。"}
        report = normalize(raw).report()["brief"]
        self.assertEqual(report["goal"]["primary"], "store_visit")
        self.assertEqual(report["creative"]["format"], "story")
        self.assertEqual(report["conversion"], {"action": "claim_coupon", "destination": "门店小程序"})
        self.assertIn({"field": "creative.format", "value": "story"}, report["soft_preferences"])
        empty = normalize({"brief_text": "主目标："})
        self.assertEqual(empty.invalid_fields["goal"][0]["code"], "EMPTY")
