import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from src.claims import unsupported_clauses
from src.main import DATA, load_json, load_materials
from src.remote import RemoteProducer
from src.schema import Beat, Draft, Material, Scene
from src.studio import Studio
from src.tools import LocalTools

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "examples/inputs"


def fixture_choice(payload):
    """Protocol fixture only; this deliberately is not model evidence."""
    action = next(a for a in payload['allowed_actions'] if a != 'STOP')
    result = {'action': action, 'reason': '协议测试预设动作，不是真实模型决策'}
    if action == 'FIND_MATERIAL':
        result['query'] = payload['action_options'][action].get('query', '')
    if action == 'SELECT_CONCEPT':
        result['plan_id'] = payload['plans'][0]['id']
    return result


class RequirementsTests(unittest.TestCase):
    def cli(self, name, *args, env=None):
        run = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "src.main", "--creative-mode", "legacy", str(INPUTS / name), "--json", *args],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env,
        )
        return run.returncode, json.loads(run.stdout)

    def test_p01_revises_duration_and_retains_scene_evidence(self):
        code, output = self.cli("campaign_p01.txt", "--creative-mode", "planned")
        self.assertEqual((code, output["status"]), (0, "COMPLETED"))
        self.assertEqual(output["script_version"], 2)
        self.assertLessEqual(output["checks"]["duration"]["total_seconds"], 15)
        scenes = output["script"]["scenes"]
        self.assertEqual(sum(s["estimated_seconds"] for s in scenes), output["script"]["estimated_seconds"])
        payoff = next(s for s in scenes if s["purpose"] == "payoff")
        self.assertEqual(payoff["voiceover"], "支持字幕。")
        self.assertEqual(payoff["evidence"], [{"material_id": "P01", "source": "合成字幕录屏 P01", "fact": "支持字幕"}])
        self.assertEqual(output["checks"]["review"]["version"], 2)

    def test_unsupported_opening_claim_is_cited_in_failure_output(self):
        code, output = self.cli("raw_unbacked_claim.txt")
        self.assertEqual((code, output["status"]), (2, "QUALITY_FAILED"))
        self.assertIsNone(output["script"])
        issue = output["checks"]["rules_and_claims"]["issues"][0]
        self.assertEqual((issue["scene_id"], issue["field"], issue["code"]),
                         ("S01", "voiceover", "UNSUPPORTED_CLAIM"))

    def test_unsafe_user_title_is_not_copied_to_deliverable(self):
        code, output = self.cli("raw_rule_repaired.txt")
        # The topic is not evidence for a title claim; generate a neutral title.
        self.assertEqual((code, output["status"]), (0, "COMPLETED"))
        self.assertNotIn("全网第一", output["script"]["title"])
        self.assertTrue(output["checks"]["rules_and_claims"]["passed"])

    def test_amount_and_offer_qualifiers_cannot_be_dropped(self):
        source = ("周末到店指定拿铁立减15元",)
        self.assertTrue(unsupported_clauses("5元", source))
        self.assertTrue(unsupported_clauses("指定拿铁立减15元", source))
        self.assertFalse(unsupported_clauses("周末到店，指定拿铁立减15元", source))
        self.assertTrue(unsupported_clauses("支持字幕", ("不支持字幕",)))
        self.assertTrue(unsupported_clauses("剪辑效率提升８０％", ("支持字幕",)))

    def test_material_visual_cannot_add_claim_beyond_fact_record(self):
        material = Material("P01", "剪影工作台", (), (), "支持字幕",
                            "画面标明支持字幕并宣称效率提升80%")
        beat = Beat("S01", "payoff", material.visual, "支持字幕。", material_id="P01")
        result = LocalTools((material,), ()).check_brand(Draft("字幕演示", (beat,)),
                                                         (Scene(beat, 4, 4),), (material,))
        self.assertFalse(result["passed"])
        self.assertEqual(result["issues"][0]["field"], "action")
        self.assertEqual(result["issues"][0]["material_ids"], ["P01"])

    def test_same_brief_changes_next_action_when_only_catalog_changes(self):
        brief = load_json(INPUTS / "normal.json")
        choices = []

        def choose(payload):
            choices.append(payload)
            if payload["search_count"] and not payload["materials"]:
                return {"action": "ASK", "reason": "素材为空，请补充同款材料。"}
            return fixture_choice(payload)

        present = Studio(RemoteProducer(choose), LocalTools(load_materials(DATA / "materials.json"), ()), creative_mode="legacy").run(brief)
        absent = Studio(RemoteProducer(choose), LocalTools((), ()), creative_mode="legacy").run(brief)
        self.assertEqual(present["trace"][0]["next_action"], "WRITE")
        self.assertEqual(absent["trace"][0]["next_action"], "ASK")
        self.assertEqual(absent["trace"][1]["decision_source"], "llm")
        empty = [p for p in choices if p["observations"] and p["observations"][0]["result"] == []]
        self.assertEqual(len(empty), 1)
        self.assertEqual(present["llm_decisions"], len(present["trace"]))

    def test_invalid_remote_choice_stops_without_offline_fallback(self):
        brief = load_json(INPUTS / "shorter.json")
        models = RemoteProducer(lambda _: {"action": "DELIVER", "reason": "直接交付"})
        output = Studio(models, LocalTools(load_materials(DATA / "materials.json"), ()), creative_mode="legacy").run(brief)
        self.assertEqual(output["status"], "MODEL_FAILED")
        self.assertIsNone(output["script"])
        self.assertEqual(output["trace"][-1]["action"], "MODEL_FAILED")

    def test_model_mode_http_sends_actual_duration_and_uses_returned_action(self):
        observed = []
        from remote_fixtures import FullFixture
        full_fixture = FullFixture()

        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prompt = json.loads(request["messages"][1]["content"])
                observed.append(prompt)
                choice = full_fixture(prompt)
                response = {"choices": [{"message": {"content": json.dumps(choice)}}]}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Endpoint)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = {**os.environ, "STUDIO_LLM_URL": f"http://127.0.0.1:{server.server_port}/chat/completions",
                   "STUDIO_LLM_MODEL": "local-protocol-test", "STUDIO_LLM_KEY": ""}
            code, output = self.cli("campaign_p01.txt", "--creative-mode", "planned", "--model", "llm", env=env)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual((code, output["status"], output["model_mode"]), (0, "COMPLETED", "llm"))
        self.assertEqual(len(observed), output['audit']['model_calls'])
        self.assertGreater(len(observed), 8)
        duration_observations = [p['checks']['duration'] for p in observed
                                 if p['task']=='producer' and p['last_event'].get('action') == 'CHECK']
        self.assertGreater(duration_observations[0]['total_seconds'], 15)
        self.assertLessEqual(duration_observations[-1]['total_seconds'], 15)
        self.assertIn('DELIVER', observed[-1]['allowed_actions'])
        self.assertEqual(observed[-1]['checks']['version'], output['script_version'])
        self.assertEqual(output['decision_model']['name'], 'local-protocol-test')
