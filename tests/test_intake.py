import json
import subprocess
import sys
import unittest
from pathlib import Path

from src.intake import normalize, split_text

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "examples" / "inputs"


def raw(name):
    return split_text((INPUTS / name).read_text(encoding="utf-8"))


class IntakeTests(unittest.TestCase):
    def test_mixed_text_maps_fields_and_keeps_provenance(self):
        intake = normalize(raw("raw_brief.txt"))
        self.assertEqual(intake.questions, [])
        self.assertEqual(intake.fields["target_seconds"], 30)
        self.assertEqual(intake.fields["platform"], "抖音")
        self.assertEqual(intake.fields["aspect_ratio"], "9:16")
        self.assertEqual(intake.fields["style"], "轻快直接")
        self.assertEqual(intake.sources["target_seconds"]["selected"]["text"], "时长控制在0.5分钟内")
        self.assertEqual([m.id for m in intake.materials], ["M01", "P02"])
        self.assertEqual(intake.materials[0].source, "活动确认单")
        self.assertEqual([rule["kind"] for rule in intake.rules], ["banned", "required"])
        self.assertEqual(intake.notes[0]["text"], "优先用报名页录屏和市集入口实拍")

    def test_conflict_only_resolved_by_explicit_confirmation(self):
        request = raw("raw_conflict.txt")
        intake = normalize(request)
        self.assertNotIn("target_seconds", intake.fields)
        self.assertEqual([option["value"] for option in intake.conflicts["target_seconds"]], [30, 45])
        resolved = normalize({**request, "confirmed": {"target_seconds": 45}})
        self.assertFalse(resolved.questions)
        self.assertEqual(resolved.fields["target_seconds"], 45)
        self.assertEqual(resolved.sources["target_seconds"]["selected"]["kind"], "confirmed")
        self.assertEqual(len(resolved.sources["target_seconds"]["candidates"]), 3)

    def test_inexact_duration_and_unknown_brand_rule_need_clarification(self):
        request = raw("raw_brief.txt")
        intake = normalize({**request, "brief_text": request["brief_text"].replace("0.5分钟", "25到30秒"),
                            "brand_notes": "到店宣传要显得更高级"})
        self.assertNotIn("target_seconds", intake.fields)
        self.assertTrue(any("明确的时长上限" in question for question in intake.questions))
        self.assertTrue(any("尚无法自动核验" in question for question in intake.questions))

    def test_conflicting_material_id_and_brand_terms_need_clarification(self):
        request = raw("raw_brief.txt")
        materials = request["material_notes"] + (
            "\n[P02] 主体：岸边手作市集｜事实：入口可扫码领活动地图｜画面：扫码后出现地图页｜来源：合成活动卡"
        )
        intake = normalize({**request, "material_notes": materials, "brand_notes": "必须说出「全网第一」"},
                           baseline_banned=("全网第一",))
        self.assertEqual([item.id for item in intake.materials], ["M01"])
        self.assertEqual(len(intake.material_sources["P02"]), 2)
        self.assertTrue(any("素材 ID P02" in question for question in intake.questions))
        self.assertTrue(any("品牌规则冲突" in question for question in intake.questions))

    def test_missing_brand_rules_are_not_treated_as_no_rules(self):
        request = raw("raw_brief.txt")
        intake = normalize({**request, "brand_notes": ""})
        self.assertTrue(any("无额外品牌规则" in question for question in intake.questions))

    def test_unclassified_hard_constraint_blocks_intake(self):
        request = raw("raw_brief.txt")
        intake = normalize({**request, "brief_text": request["brief_text"] + "\n不得出现竞品。"})
        self.assertTrue(any("未归类的强制要求" in question for question in intake.questions))

    def run_cli(self, name, *flags):
        command = [sys.executable, "-X", "utf8", "-m", "src.main", "--creative-mode", "legacy",
                   str(INPUTS / name), *flags, "--json"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        return result.returncode, json.loads(result.stdout)

    def test_cli_uses_request_materials_not_demo_fixtures(self):
        code, result = self.run_cli("raw_brief.txt")
        self.assertEqual((code, result["status"]), (2, "NEEDS_REVIEW"))
        self.assertEqual(result["creative"]["evidence_pack"]["facts"][0]["id"], "P02")
        self.assertEqual(result["intake"]["materials"][0]["source"], "活动确认单")

    def test_cli_brief_only_is_a_separate_reviewable_stage(self):
        code, result = self.run_cli("raw_brief.txt", "--brief-only")
        self.assertEqual((code, result["status"]), (0, "READY"))
        self.assertNotIn("script", result)

    def test_explicit_material_attachment_keeps_its_origin(self):
        code, result = self.run_cli("raw_brief.txt", "--brief-only",
                                    "--materials", str(ROOT / "data" / "materials.json"))
        self.assertEqual((code, result["status"]), (2, "NEEDS_INPUT"))
        self.assertTrue(any("笔记和附件中不一致" in item for item in result["intake"]["questions"]))
        self.assertEqual(result["intake"]["material_sources"]["P01"][0]["source"], "materials.json#P01")

    def test_cli_conflict_and_unsatisfied_brand_rule_gate_delivery(self):
        code, conflict = self.run_cli("raw_conflict.txt")
        self.assertEqual((code, conflict["status"]), (2, "NEEDS_INPUT"))
        self.assertIsNone(conflict["script"])
        code, blocked = self.run_cli("raw_rule_blocked.txt")
        self.assertEqual((code, blocked["status"]), (2, "QUALITY_FAILED"))
        self.assertIsNone(blocked["script"])
