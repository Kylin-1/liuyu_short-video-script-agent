"""Regression tests for concrete reviewer repros, not only happy-path fixtures."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from src.main import DATA, load_rule_config, run_request
from src.schema import InputError, Material
from src.models import MockModels
from src.remote import RemoteProducer
from src.studio import Studio
from src.tools import LocalTools
from test_creative import request, run
from test_requirements import fixture_choice


class GroundingTests(unittest.TestCase):
    def test_unbacked_synonyms_and_numbers_cannot_pass_unknown_fields(self):
        for claim in ('这只杯子仅重200克，放包里没负担。', '装进包里完全不会漏水。',
                      '随便倒着放也不用担心水洒出来。', '专业运动员都在用。'):
            for field in ('hook_line', 'turn_line', 'opening', 'resolution'):
                with self.subTest(claim=claim, field=field):
                    result = run({**request().fields, field: claim})
                    self.assertEqual(result['status'], 'NEEDS_REVIEW')
                    self.assertIsNone(result['script'])
                    self.assertTrue(any(claim in i['value'] for i in result['checks']['grounding']['issues']))

    def test_reference_repair_removes_only_unverified_fields_and_rechecks(self):
        result = run({**request().fields, 'creative_policy': 'reference',
                      'hook_line': '这只杯子仅重200克，放包里没负担。'})
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual([e['action'] for e in result['trace']].count('CHECK'), 2)
        self.assertIn('REPAIR_UNVERIFIED', [e['action'] for e in result['trace']])
        original = next(e['observation']['beats'] for e in result['trace'] if e['action'] == 'WRITE')
        final = result['script']['scenes']
        self.assertNotIn('200克', json.dumps(result['script'], ensure_ascii=False))
        for old, new in zip(original, final):
            self.assertEqual((old['action'], old['subtitle']), (new['visual'], new['subtitle']))
            if old['id'] != 'S01':
                self.assertEqual(old['voiceover'], new['voiceover'])
        self.assertEqual(result['checks']['grounding']['policy_version'], 'grounding-v1')

    def test_unrelated_moon_story_is_not_certified_by_keyword_critic(self):
        result = run({**request().fields, 'turn': '他突然想起明天的数学考试，转身去找课本。',
                      'resolution': '随后镜头切到月球，宇航员向镜头招手。'})
        self.assertEqual(result['status'], 'NEEDS_REVIEW')
        self.assertIsNone(result['script'])

    def test_valid_custom_narrative_is_also_deferred_and_labeled_unknown(self):
        result = run({**request().fields, 'hook_line': '电梯到了，等我一下。'})
        self.assertEqual(result['status'], 'NEEDS_REVIEW')
        self.assertEqual(result['checks']['grounding']['issues'][0]['code'], 'UNVERIFIED_CONTENT')
        # This is an intentional coverage limit, not a fabricated factual error.
        self.assertNotIn('UNSUPPORTED_CLAIM', json.dumps(result['checks']['grounding']))

    def test_exact_fact_in_hook_gets_a_scene_level_citation(self):
        result = run({**request().fields, 'hook_line': '杯盖带滑动锁扣。'})
        self.assertEqual(result['status'], 'COMPLETED')
        hook = result['script']['scenes'][0]
        self.assertEqual(hook['material_ids'], ['D01'])
        record = next(r for r in hook['field_provenance'] if r['field'] == 'voiceover')
        self.assertEqual(record['quotes'], ['杯盖带滑动锁扣'])
        self.assertEqual(record['status'], 'VERIFIED')

    def test_bogus_specialist_title_is_not_trusted(self):
        class Invented(MockModels):
            def write_concept(self, *args):
                return replace(super().write_concept(*args), title='只重200克的杯子')
        self.assertEqual(run(models=Invented())['status'], 'NEEDS_REVIEW')

    def test_missing_style_is_required_even_if_goal_exists(self):
        result = run({**request().fields, 'style': ''})
        self.assertEqual(result['status'], 'NEEDS_INPUT')
        self.assertIn('风格', result['requested_fields'])
        self.assertEqual(result['audit']['tool_calls'], 0)

    def test_model_observes_success_and_empty_result_on_different_paths(self):
        seen = []
        def choose(payload):
            seen.append(payload)
            if payload['search_count'] and not payload['materials']:
                return {'action': 'ASK', 'reason': '无同主体素材，请补充。'}
            return fixture_choice(payload)
        good = run(models=RemoteProducer(choose))
        empty = Studio(RemoteProducer(choose), LocalTools((), ())).run(request().fields)
        self.assertEqual(good['status'], 'COMPLETED')
        self.assertEqual(good['llm_decisions'], len(good['trace']))
        self.assertEqual(empty['status'], 'MATERIAL_REQUIRED')
        self.assertEqual([e['action'] for e in empty['trace']], ['FIND_MATERIAL', 'ASK'])
        self.assertTrue(all(e['decision_source'] == 'llm' for e in good['trace']))
        self.assertEqual(good['decision_model']['transport'], 'injected')

    def test_model_observes_retry_errors_and_can_decline_retry(self):
        seen=[]
        def choose(payload):
            seen.append(payload)
            if payload['last_event'].get('status') == 'tool_error':
                return {'action': 'STOP', 'reason': '工具不可用，停止并说明失败。'}
            return fixture_choice(payload)
        i=request()
        result=Studio(RemoteProducer(choose),LocalTools(i.materials,(), 'search_material', 1)).run(i.fields)
        self.assertEqual(result['status'], 'TOOL_FAILED')
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[-1]['observations'][0]['result']['status'], 'error')

    def test_model_can_refuse_delivery_after_passing_recheck(self):
        seen=[]
        def choose(payload):
            seen.append(payload)
            if 'DELIVER' in payload['allowed_actions']:
                return {'action':'STOP','reason':'工具通过，创意仍需确认。'}
            return fixture_choice(payload)
        result=run(models=RemoteProducer(choose))
        self.assertEqual(result['status'],'QUALITY_FAILED')
        self.assertTrue(seen[-1]['checks']['grounding']['passed'])
        self.assertIsNone(result['script'])

    def test_rule_json_required_terms_are_enforced_and_unknown_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            rules=Path(directory)/'rules.json'
            rules.write_text(json.dumps({'banned_terms':[], 'required_terms':['仅限周末到店使用']}))
            args=SimpleNamespace(input=Path('examples/inputs/normal.json'), rules=rules, materials=None,
                brief_only=False, model='mock', fail_tool=None, fail_times=0, max_steps=20,
                max_tool_calls=10,creative_mode='planned')
            result=run_request(args)
            self.assertEqual(result['status'],'QUALITY_FAILED')
            self.assertTrue(any(i['code']=='REQUIRED_TERM_MISSING' for i in result['checks']['rules_and_claims']['issues']))
            rules.write_text(json.dumps({'banned_terms':[], 'required_term':['拼错的字段']}))
            with self.assertRaises(InputError):load_rule_config(rules)

    def test_cross_source_rule_conflict_is_rejected_before_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            rules=Path(directory)/'rules.json'
            rules.write_text(json.dumps({'banned_terms':[], 'required_terms':['绝对防漏']}))
            args=SimpleNamespace(input=Path('examples/inputs/raw_intent_story.txt'), rules=rules, materials=None,
                brief_only=False, model='mock', fail_tool=None, fail_times=0,max_steps=20,
                max_tool_calls=10,creative_mode='planned')
            with self.assertRaises(InputError):run_request(args)
