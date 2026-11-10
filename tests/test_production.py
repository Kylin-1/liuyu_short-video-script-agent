import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.intake import normalize, split_text
from src.models import MockModels
from src.studio import Studio
from src.tools import LocalTools

ROOT = Path(__file__).resolve().parents[1]


class ProductionTests(unittest.TestCase):
    def run_case(self, name):
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "trace.json"
            run = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "src.main", "--creative-mode", "legacy", f"examples/inputs/{name}.txt",
                 "--json", "--trace", str(trace_path)],
                cwd=ROOT, capture_output=True, encoding="utf-8", check=False,
            )
            return run.returncode, json.loads(run.stdout), json.loads(trace_path.read_text(encoding="utf-8"))

    def test_locked_custom_story_is_preserved_as_draft_but_not_certified(self):
        code, result, trace = self.run_case("raw_production")
        self.assertEqual((code, result["status"]), (2, "NEEDS_REVIEW"))
        self.assertIsNone(result["script"])
        fields = result["intake"]["fields"]
        self.assertEqual(fields["format"], "sales_story")
        draft = next(e["observation"] for e in trace["steps"] if e["action"] == "WRITE")
        self.assertEqual([b['purpose'] for b in draft['beats']], ['hook','turn','operation','payoff','resolution'])
        self.assertIn('一把拽住包带', draft['beats'][0]['action'])
        self.assertIn('接过包跨进电梯', draft['beats'][-1]['action'])
        self.assertTrue(result['checks']['grounding']['issues'])
        self.assertEqual(trace["steps"][0]["calls"][0]["params"]["material_id"], "D01")

    def test_missing_turn_is_now_a_creative_task(self):
        source = (ROOT / "examples/inputs/raw_production.txt").read_text(encoding="utf-8")
        raw = split_text("\n".join(line for line in source.splitlines() if not line.startswith("转折动作：")))
        intake = normalize(raw)
        self.assertNotIn("转折动作", intake.missing)
        self.assertFalse(intake.questions)

    def test_sales_topic_identifies_goal_without_locking_story(self):
        raw = {"brief_text": "主题：随行杯带货", "brand_notes": "无额外品牌规则"}
        intake = normalize(raw)
        self.assertEqual(intake.fields["goal"], "purchase")
        self.assertNotIn("format", intake.fields)
        self.assertIn("承接入口", intake.missing)

    def test_sales_story_rejects_an_otherwise_valid_product_demo(self):
        class DisplayOnly(MockModels):
            def screenwriter(self, brief, materials):
                return super().screenwriter(replace(brief, format="demo"), materials)

        source = (ROOT / "examples/inputs/raw_production.txt").read_text(encoding="utf-8")
        intake = normalize(split_text(source))
        self.assertFalse(intake.questions)
        tools = LocalTools(intake.materials, (), required=("杯盖带滑动锁扣",))
        from src.schema import Brief
        brief, _ = Brief.parse(intake.fields)
        models = DisplayOnly()
        draft = models.screenwriter(brief, intake.materials)
        scenes = models.director(brief, draft, False)
        review = models.reviewer(brief, draft, scenes, intake.materials)
        self.assertIn('SALES_STORY_INCOMPLETE', [issue['code'] for issue in review['issues']])

    def test_short_budget_preserves_clean_plot_and_fact(self):
        intake = normalize(split_text((ROOT / 'examples/inputs/raw_intent_story.txt').read_text()))
        def generate(seconds):
            return Studio(MockModels(), LocalTools(intake.materials, ())).run({**intake.fields, 'target_seconds': seconds})
        longer, shorter = generate(30), generate(15)
        self.assertEqual(shorter['status'], 'COMPLETED')
        self.assertIn('COMPACT_SCENES', [e['action'] for e in shorter['trace']])
        self.assertLessEqual(shorter['script']['estimated_seconds'], 15)
        for result in (longer, shorter):
            payoff = next(s for s in result['script']['scenes'] if s['purpose'] == 'payoff')
            self.assertEqual(payoff['voiceover'], '杯盖带滑动锁扣。')
            self.assertEqual(payoff['material_ids'], ['D01'])
            self.assertEqual(result['script']['scenes'][-1]['subtitle'], '点开视频下方商品卡，看商品详情')

    def test_requested_result_cannot_borrow_footage_from_another_product(self):
        code, result, trace = self.run_case("raw_proof_gap")
        self.assertEqual((code, result["status"]), (2, "MATERIAL_REQUIRED"))
        self.assertIsNone(result["script"])
        self.assertEqual([step["action"] for step in trace["steps"]], ["FIND_MATERIAL", "ASK"])
        self.assertEqual(result["requested_fields"], ["操作画面及结果证据"])

    def test_same_contract_for_store_traffic_campaign(self):
        code, result, _ = self.run_case("campaign_store")
        self.assertEqual((code, result["status"]), (0, "COMPLETED"))
        scenes = result["script"]["scenes"]
        operation = next(s for s in scenes if s['purpose'] == 'operation')
        payoff = next(s for s in scenes if s['purpose'] == 'payoff')
        self.assertIn('点击「领券」', operation['visual'])
        self.assertIn('券码页显示核销成功', payoff['visual'])
        self.assertEqual(payoff['material_ids'], ['T02'])
        self.assertEqual(payoff['voiceover'], '周末到店指定拿铁立减5元，须出示小程序券码。')
