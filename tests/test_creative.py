import json
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from src.intake import normalize, split_text
from test_requirements import fixture_choice
from src.models import MockModels
from src.remote import RemoteProducer
from src.schema import Decision, ModelError
from src.studio import Studio
from src.tools import LocalTools

ROOT = Path(__file__).resolve().parents[1]


def request(name='raw_intent_story'):
    intake = normalize(split_text((ROOT / f'examples/inputs/{name}.txt').read_text(encoding='utf-8')))
    assert not intake.questions, intake.questions
    return intake


def run(fields=None, models=None, mode='planned', **kwargs):
    intake = request()
    return Studio(models or MockModels(), LocalTools(intake.materials, ('绝对防漏',)),
                  creative_mode=mode, **kwargs).run(fields or intake.fields)


def reference():
    return {**request().fields, 'creative_policy': 'reference', 'hook_line': '大家好，今天给你介绍一款产品。'}


class CreativeTests(unittest.TestCase):
    def test_minimal_business_brief_plans_before_writing(self):
        result = run()
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual([step['action'] for step in result['trace']],
                         ['FIND_MATERIAL', 'PLAN', 'SELECT_CONCEPT', 'WRITE', 'DIRECT', 'CHECK', 'REVIEW', 'CRITIQUE', 'DELIVER'])
        self.assertEqual(len(result['creative']['plans']), 2)
        self.assertEqual(result['creative']['selected_plan_id'], 'C01')
        self.assertTrue(all(plan['assumptions'] and plan['audience_insight'] for plan in result['creative']['plans']))
        self.assertIn('锁扣', result['script']['scenes'][1]['voiceover'])
        self.assertEqual(result['script']['scenes'][-1]['subtitle'], '点开视频下方商品卡，看商品详情')
        self.assertTrue(result['checks']['creative_review']['human_review_required'])

    def test_reference_hook_is_rewritten_and_all_checks_are_rerun(self):
        result = run(reference())
        self.assertEqual(result['status'], 'COMPLETED')
        actions = [step['action'] for step in result['trace']]
        self.assertEqual(actions.count('REWRITE_CREATIVE'), 1)
        self.assertEqual(actions.count('CHECK'), 2)
        self.assertEqual(actions.count('REVIEW'), 2)
        self.assertEqual(actions.count('CRITIQUE'), 2)
        critiques = [step['observation'] for step in result['trace'] if step['action'] == 'CRITIQUE']
        issue = critiques[0]['issues'][0]
        self.assertEqual((issue['scene_id'], issue['field'], issue['code']), ('S01', 'voiceover', 'GENERIC_HOOK'))
        self.assertEqual(issue['evidence'], reference()['hook_line'])
        self.assertTrue(issue['revision_goal'] and issue['preserve'])
        self.assertNotIn('大家好', result['script']['scenes'][0]['voiceover'])
        self.assertEqual(result['checks']['creative_review']['version'], 2)
        original = next(step['observation'] for step in result['trace'] if step['action'] == 'WRITE')
        final = {scene['id']: scene for scene in result['script']['scenes']}
        for beat in original['beats']:
            if beat['id'] != 'S01':
                self.assertEqual((beat['action'], beat['voiceover'], beat['subtitle']),
                                 (final[beat['id']]['visual'], final[beat['id']]['voiceover'], final[beat['id']]['subtitle']))

    def test_locked_weak_hook_requires_confirmation(self):
        result = run({**reference(), 'creative_policy': 'locked'})
        self.assertEqual(result['status'], 'QUALITY_FAILED')
        self.assertIsNone(result['script'])
        self.assertNotIn('REWRITE_CREATIVE', [step['action'] for step in result['trace']])
        self.assertIn('锁定', result['detail'])

    def test_no_effect_rewrite_stops_at_shared_revision_budget(self):
        class NoChange(MockModels):
            def rewrite_creative(self, brief, plan, draft, issues):
                return draft
        result = run(reference(), NoChange())
        self.assertEqual(result['status'], 'REVISION_LIMIT')
        self.assertEqual(result['creative']['revision_count'], 2)
        self.assertIsNone(result['script'])

    def test_rewrite_cannot_change_fact_or_cta(self):
        for target in ('payoff', 'resolution'):
            class Unsafe(MockModels):
                def rewrite_creative(self, brief, plan, draft, issues):
                    value = super().rewrite_creative(brief, plan, draft, issues)
                    return replace(value, beats=tuple(replace(beat, voiceover='效率提升80%')
                                   if beat.purpose == target else beat for beat in value.beats))
            with self.subTest(target=target):
                result = run(reference(), Unsafe())
                self.assertEqual(result['status'], 'MODEL_FAILED')
                self.assertIsNone(result['script'])

    def test_critic_must_quote_the_actual_script(self):
        class InventedEvidence(MockModels):
            def critique(self, *args):
                report = super().critique(*args)
                report['issues'][0]['evidence'] = '原稿没有写过的句子'
                return report
        self.assertEqual(run(reference(), InventedEvidence())['status'], 'MODEL_FAILED')

    def test_stale_creative_review_cannot_authorize_delivery(self):
        class Skip(MockModels):
            def producer(self, state):
                if state.last.get('action') == 'CRITIQUE':
                    return Decision('DIRECT', '重新排镜')
                if state.version == 2:
                    return Decision('DELIVER', '跳过新评审')
                return super().producer(state)
        self.assertEqual(run(models=Skip())['status'], 'INVALID_ACTION')

    def test_invalid_plan_reference_is_rejected(self):
        class WrongPlan(MockModels):
            def propose_concepts(self, brief, materials):
                plans = super().propose_concepts(brief, materials)
                return (replace(plans[0], material_ids=('other-product',)),)
        self.assertEqual(run(models=WrongPlan())['status'], 'MODEL_FAILED')

    def test_direct_delivery_without_creative_review_is_rejected(self):
        class Skip(MockModels):
            def producer(self, state):
                if state.review and state.review['passed']:
                    return Decision('DELIVER', '跳过创作诊断')
                return super().producer(state)
        self.assertEqual(run(models=Skip())['status'], 'INVALID_ACTION')

    def test_no_material_stops_before_creative_proposals(self):
        result = Studio(MockModels(), LocalTools((), ())).run(request().fields)
        self.assertEqual(result['status'], 'MATERIAL_REQUIRED')
        self.assertEqual(result['creative']['plans'], [])

    def test_new_role_failure_is_explicit(self):
        class Failed(MockModels):
            def propose_concepts(self, *args):
                raise ModelError('创意方案服务不可用')
        self.assertEqual(run(models=Failed())['status'], 'MODEL_FAILED')

    def test_same_material_changes_with_goal_and_format(self):
        story = run()
        demo = run({**request().fields, 'format': 'demo'})
        store = run({**request().fields, 'goal': 'store_visit', 'conversion_action': 'claim_coupon',
                     'conversion_destination': '门店小程序'})
        self.assertEqual([story['status'], demo['status'], store['status']], ['COMPLETED'] * 3)
        self.assertEqual(story['script']['material_ids'], demo['script']['material_ids'])
        self.assertNotEqual([scene['purpose'] for scene in story['script']['scenes']],
                            [scene['purpose'] for scene in demo['script']['scenes']])
        self.assertNotEqual(story['script']['scenes'][0]['visual'], store['script']['scenes'][0]['visual'])
        self.assertIn('门店小程序', store['script']['scenes'][-1]['subtitle'])

    def test_legacy_is_an_explicit_comparison_baseline(self):
        old, new = run(mode='legacy'), run()
        self.assertEqual([old['status'], new['status']], ['COMPLETED', 'COMPLETED'])
        self.assertEqual(old['creative']['plans'], [])
        self.assertNotEqual(old['script']['scenes'][0]['visual'], new['script']['scenes'][0]['visual'])
        self.assertEqual(old['script']['material_ids'], new['script']['material_ids'])

    def test_cli_defaults_to_new_flow(self):
        process = subprocess.run([sys.executable, '-m', 'src.main', 'examples/inputs/raw_intent_story.txt', '--json'],
                                 cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['creative_mode'], 'planned')

    def test_remote_decision_can_decline_a_creative_rewrite(self):
        seen = []
        def choose(payload):
            seen.append(payload)
            if 'REWRITE_CREATIVE' in payload['allowed_actions']:
                return {'action': 'STOP', 'reason': '先确认参考开场的使用范围。'}
            return fixture_choice(payload)
        result = run(reference(), RemoteProducer(choose))
        self.assertEqual(result['status'], 'QUALITY_FAILED')
        self.assertEqual(result['llm_decisions'], len(seen))
        self.assertEqual(seen[-1]['creative_review']['issues'][0]['code'], 'GENERIC_HOOK')

    def test_creative_policy_is_extracted_and_evidenced(self):
        source = (ROOT / 'examples/inputs/raw_intent_story.txt').read_text(encoding='utf-8')
        source = source.replace('【制作需求】', '【制作需求】\n创意要求策略：仅供参考；开场台词：大家好。')
        intake = normalize(split_text(source))
        self.assertEqual(intake.fields['creative_policy'], 'reference')
        self.assertEqual(intake.sources['creative_policy']['selected']['kind'], 'brief_text')
        self.assertTrue(any(item.get('field') == 'creative.user_requirements.hook_line' for item in intake.report()['brief']['soft_preferences']))

    def test_reference_motivation_and_ending_are_repaired_together(self):
        intake = request('raw_creative_reference')
        result = run(intake.fields)
        self.assertEqual(result['status'], 'COMPLETED')
        first = next(step['observation'] for step in result['trace'] if step['action'] == 'CRITIQUE')
        self.assertEqual({item['code'] for item in first['issues']},
                         {'GENERIC_HOOK', 'MISSING_MOTIVATION', 'UNRESOLVED_PAYOFF'})
        self.assertEqual(result['creative']['revision_count'], 1)
        self.assertEqual(result['script']['material_ids'], ['D01'])

    def test_unverified_locked_copy_is_preserved_and_deferred(self):
        intake = request('raw_reference_p01')
        result = Studio(MockModels(), LocalTools(intake.materials, ())).run(intake.fields)
        self.assertEqual(result['status'], 'NEEDS_REVIEW')
        self.assertIsNone(result['script'])
        original = next(e['observation'] for e in result['trace'] if e['action'] == 'WRITE')
        self.assertEqual(original['beats'][0]['voiceover'], intake.fields['hook_line'])
        self.assertNotIn('REPAIR_UNVERIFIED', [e['action'] for e in result['trace']])

    def test_audience_and_style_reach_concept_and_shot_instructions(self):
        fields = {**request().fields, 'audience': '准备露营的户外爱好者', 'style': '安静克制'}
        result = run(fields)
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertIn('行李整理台', result['script']['scenes'][0]['visual'])
        self.assertIn('避免突兀音效', result['script']['scenes'][0]['sound'])

    def test_planned_mode_keeps_missing_and_budget_failures_explicit(self):
        missing = run({**request().fields, 'audience': ''})
        self.assertEqual(missing['status'], 'NEEDS_INPUT')
        limited = run(max_tool_calls=2)
        self.assertEqual(limited['status'], 'TOOL_LIMIT')
        self.assertIsNone(limited['script'])

    def test_unhashable_plan_id_is_a_contract_error(self):
        class InvalidPlan(MockModels):
            def propose_concepts(self, brief, materials):
                plans = super().propose_concepts(brief, materials)
                return (replace(plans[0], id=[]),)
        self.assertEqual(run(models=InvalidPlan())['status'], 'MODEL_FAILED')

    def test_blind_forms_do_not_prepopulate_scores_or_disclose_mode(self):
        from examples.evaluate_creative import blind_forms
        form, key = blind_forms([('带货', run(mode='legacy'), run())], 7)
        self.assertEqual(form['status'], 'UNRATED')
        self.assertEqual({item['mode'] for item in key['mapping']}, {'legacy', 'planned'})
        for candidate in form['cases'][0]['candidates']:
            self.assertTrue(all(value is None for value in candidate['scores'].values()))
            self.assertNotIn('mode', candidate)
            self.assertNotIn('checks', candidate)

    def test_negative_feature_fact_does_not_trigger_positive_story_seed(self):
        from src.schema import Material
        material = Material('N01', '剪辑台', (), (), '不支持字幕', '页面显示未提供字幕功能', '合成能力说明')
        fields = {**request().fields, 'subject': '剪辑台', 'topic': '功能边界说明'}
        result = Studio(MockModels(), LocalTools((material,), ())).run(fields)
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertTrue(all(plan['focus'] == '细节' for plan in result['creative']['plans']))
        payoff = next(scene for scene in result['script']['scenes'] if scene['purpose'] == 'payoff')
        self.assertEqual(payoff['voiceover'], '不支持字幕。')
