import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.claims import unsupported_clauses
from src.main import DATA, atomic_json, load_json, load_materials, load_rules
from src.models import MockModels
from src.remote import RemoteProducer
from src.schema import Decision, Material, ModelError
from src.studio import Studio
from src.tools import LocalTools, read_units

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'examples/inputs'


def make_tools(cls=LocalTools, required=()):
    return cls(load_materials(DATA / 'materials.json'), load_rules(DATA / 'brand_rules.json'),
               required=required)


def run(models=None, tools=None, name='normal', **kwargs):
    return Studio(models or MockModels(), tools or make_tools(), **kwargs, creative_mode="legacy").run(load_json(INPUTS / f'{name}.json'))


class ReliabilityTests(unittest.TestCase):
    def test_feature_scope_cannot_be_removed(self):
        for fact in ('仅专业版支持字幕', '需开通会员，支持字幕', '仅部分型号支持字幕', '无需会员，支持字幕'):
            with self.subTest(fact=fact):
                self.assertTrue(unsupported_clauses('支持字幕', (fact,)))
                self.assertFalse(unsupported_clauses(fact, (fact,)))
        self.assertTrue(unsupported_clauses('无需会员，支持字幕', ('需会员，支持字幕',)))

    def test_fullwidth_numbers_have_the_same_duration_weight(self):
        self.assertEqual(read_units('效率提升８０％'), read_units('效率提升80%'))

    def test_fullwidth_brand_term_is_not_a_bypass(self):
        class Writer(MockModels):
            def screenwriter(self, brief, materials):
                return replace(super().screenwriter(brief, materials), title='ＡＢＣ商品演示')
        tools = LocalTools(load_materials(DATA / 'materials.json'), ('ABC',))
        self.assertEqual(run(Writer(), tools)['status'], 'QUALITY_FAILED')

    def test_missing_disclosure_is_added_only_with_cited_evidence(self):
        term = '仅限周末到店使用'
        source = Material('R01', '岩途随行杯', (), ('锁扣',), term, '活动规则页显示完整使用条件', '合成活动规则')
        tools = LocalTools((*load_materials(DATA / 'materials.json'), source), (), required=(term,))
        result = run(tools=tools)
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertIn('ADD_DISCLOSURE', [step['action'] for step in result['trace']])
        self.assertEqual(sum(step['action'] == 'CHECK' for step in result['trace']), 2)
        disclosure = next(scene for scene in result['script']['scenes'] if scene['purpose'] == 'disclaimer')
        self.assertEqual(disclosure['evidence'][0]['fact'], term)
        self.assertEqual(disclosure['material_ids'], ['R01'])
        self.assertEqual(result['script']['scenes'][-1]['purpose'], 'close')
        self.assertEqual(result['checks']['version'], 2)

    def test_brand_requirement_does_not_authorize_a_new_fact(self):
        result = run(tools=make_tools(required=('效率提升80%',)))
        self.assertEqual(result['status'], 'QUALITY_FAILED')
        self.assertNotIn('ADD_DISCLOSURE', [step['action'] for step in result['trace']])
        self.assertIsNone(result['script'])

    def test_model_can_stop_instead_of_adding_disclosure(self):
        term = '仅限周末到店使用'
        source = Material('R01', '岩途随行杯', (), ('锁扣',), term, '活动规则页', '合成活动规则')
        tools = LocalTools((*load_materials(DATA / 'materials.json'), source), (), required=(term,))
        observed = []
        def choose(payload):
            observed.append(payload)
            from test_requirements import fixture_choice
            if 'ADD_DISCLOSURE' in payload['allowed_actions']:
                return {'action': 'STOP', 'reason': '先请用户确认是否接受新增规则镜头。'}
            return fixture_choice(payload)
        result = run(RemoteProducer(choose), tools)
        self.assertEqual(result['status'], 'QUALITY_FAILED')
        self.assertEqual(result['llm_decisions'], len(observed))
        self.assertIn('ADD_DISCLOSURE', observed[-1]['allowed_actions'])
        self.assertIn('R01', [m['id'] for m in observed[-1]['materials']])
        self.assertNotIn('ADD_DISCLOSURE', [step['action'] for step in result['trace']])

    def test_malformed_tool_report_stops_without_retry(self):
        class BadReport(LocalTools):
            def check_brand(self, *args):
                return {'passed': 'true', 'issues': []}
        result = run(tools=make_tools(BadReport))
        self.assertEqual(result['status'], 'TOOL_FAILED')
        self.assertIsNone(result['script'])
        self.assertEqual(result['trace'][-1]['calls'][-1]['result']['code'], 'INVALID_TOOL_RESULT')
        self.assertEqual(result['audit']['tool_calls'], 3)
        class BadRepair(LocalTools):
            def check_brand(self, *args):
                return {'passed': False, 'issues': [{'scene_id': 'title', 'field': 'title',
                                                     'code': 'BANNED_TERM', 'value': {'bad': 'type'}}]}
        self.assertEqual(run(tools=make_tools(BadRepair))['status'], 'TOOL_FAILED')

    def test_duration_cannot_omit_reorder_or_underestimate_scenes(self):
        def omit(report):
            report['scenes'].pop()
        def reorder(report):
            report['scenes'].reverse()
        def underestimate(report):
            report['scenes'][0]['estimated_seconds'] = 1
            report['total_seconds'] = 1
            report['passed'] = True
        for mutation in (omit, reorder, underestimate):
            class BadTiming(LocalTools):
                def estimate_duration(self, *args):
                    report = super().estimate_duration(*args)
                    mutation(report)
                    return report
            with self.subTest(mutation=mutation.__name__):
                self.assertEqual(run(tools=make_tools(BadTiming))['status'], 'TOOL_FAILED')

    def test_wrong_product_or_forged_material_is_rejected(self):
        for item in (load_materials(DATA / 'materials.json')[-1],
                     replace(load_materials(DATA / 'materials.json')[0], fact='效率提升80%')):
            class WrongSearch(LocalTools):
                def search_material(self, *args):
                    return (item,)
            with self.subTest(item=item.id):
                result = run(tools=make_tools(WrongSearch))
                self.assertEqual(result['status'], 'TOOL_FAILED')
                self.assertEqual(len(result['trace']), 1)

    def test_runtime_budget_counts_failed_calls_and_partial_checks(self):
        result = run(max_tool_calls=2)
        self.assertEqual(result['status'], 'TOOL_LIMIT')
        self.assertEqual(result['audit']['tool_calls'], 2)
        self.assertIsNone(result['checks']['duration'])
        self.assertIsNone(result['script'])
        tools = make_tools()
        tools.fault, tools.fault_times = 'search_material', 2
        result = run(tools=tools, max_tool_calls=1)
        self.assertEqual((result['status'], result['audit']['tool_calls']), ('TOOL_LIMIT', 1))

    def test_transport_failure_is_sanitized_and_retried_once(self):
        class Unavailable(LocalTools):
            def search_material(self, *args):
                raise TimeoutError('provider?token=do-not-log')
        result = run(tools=make_tools(Unavailable))
        self.assertEqual((result['status'], result['audit']['tool_calls']), ('TOOL_FAILED', 2))
        self.assertNotIn('do-not-log', json.dumps(result))

    def test_specialist_failures_return_explicit_model_failure(self):
        for method in ('props', 'screenwriter', 'director', 'reviewer'):
            with self.subTest(method=method), patch.object(MockModels, method, side_effect=ModelError('角色服务不可用')):
                result = run()
                self.assertEqual(result['status'], 'MODEL_FAILED')
                self.assertIsNone(result['script'])
                self.assertEqual(result['trace'][-1]['next_action'], 'END')

    def test_invalid_specialist_contracts_fail_closed(self):
        invalid = {
            'producer': {'action': 'DELIVER'},
            'screenwriter': None,
            'director': (),
            'reviewer': {'passed': True, 'issues': [{'scene_id': 'S02', 'field': 'fact', 'code': 'UNSUPPORTED'}]},
        }
        for method, value in invalid.items():
            with self.subTest(method=method), patch.object(MockModels, method, return_value=value):
                self.assertEqual(run()['status'], 'MODEL_FAILED')

    def test_targeted_revision_cannot_change_product_evidence(self):
        class UnscopedRevision(MockModels):
            def revise_copy(self, draft, scene_ids):
                result = super().revise_copy(draft, scene_ids)
                return replace(result, title='改了无关标题')
        self.assertEqual(run(UnscopedRevision(), name='shorter')['status'], 'INVALID_ACTION')

    def test_remote_callback_timeout_does_not_silently_use_mock(self):
        def fail(_):
            raise TimeoutError('secret-provider-message')
        result = run(RemoteProducer(fail), name='shorter')
        self.assertEqual(result['status'], 'MODEL_FAILED')
        self.assertNotIn('secret-provider-message', json.dumps(result))

    def test_audit_matches_trace_and_detects_changed_input_or_material(self):
        first, second = run(), run()
        self.assertNotEqual(first['audit']['run_id'], second['audit']['run_id'])
        for key in ('input_sha256', 'materials_sha256', 'rules_sha256'):
            self.assertEqual(first['audit'][key], second['audit'][key])
        self.assertNotEqual(first['audit']['input_sha256'], run(name='shorter')['audit']['input_sha256'])
        tools = make_tools()
        tools.materials = (replace(tools.materials[0], fact='杯盖带可移动锁扣'),)
        self.assertNotEqual(first['audit']['materials_sha256'], run(tools=tools)['audit']['materials_sha256'])
        self.assertEqual(first['audit']['tool_calls'], sum(len(step['calls']) for step in first['trace']))

    def test_atomic_trace_write_keeps_previous_file_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.json'
            atomic_json(path, {'old': True})
            with patch('src.main.os.replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    atomic_json(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_trace_cannot_overwrite_input_or_hardlinked_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request.json'
            content = (INPUTS / 'normal.json').read_bytes()
            path.write_bytes(content)
            alias = Path(directory) / 'alias.json'
            alias.hardlink_to(path)
            for target in (path, alias):
                process = subprocess.run([sys.executable, '-m', 'src.main', '--creative-mode', 'legacy', str(path), '--trace', str(target)],
                                         cwd=ROOT, capture_output=True)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(path.read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
