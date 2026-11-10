import unittest
from unittest.mock import patch
from dataclasses import replace
from src.llm_studio import RemoteStudio
from src.schema import ModelError
from src.models import MockModels
from src.studio import Studio
from src.tools import LocalTools
from test_creative import request
from remote_fixtures import FullFixture


def run(fixture=None,fields=None):
    i=request()
    model=RemoteStudio(fixture or FullFixture())
    return Studio(model,LocalTools(i.materials,())).run(fields or i.fields)


class LLMStudioTests(unittest.TestCase):
    def test_all_roles_call_adapter_and_accept_novel_story(self):
        fixture=FullFixture(); result=run(fixture)
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(result['creative_model_mode'],'llm')
        self.assertIn('早餐',result['script']['title'])
        self.assertIn('阿宁',result['script']['scenes'][0]['visual'])
        roles={p['task'] for p in fixture.seen}
        self.assertEqual(roles,{'producer','plan','write','direct','grounding','review','critique'})
        self.assertEqual(result['audit']['model_calls'],len(fixture.seen))
        self.assertEqual(result['llm_decisions'],len(result['trace']))
        self.assertEqual(result['checks']['grounding']['policy_version'],'semantic-v2')
        self.assertTrue(any(r['status']=='FICTIONAL' for r in result['script']['scenes'][0]['field_provenance']))
        self.assertTrue(all(e['model_calls'] for e in result['trace']))

    def test_each_specialist_failure_is_explicit_without_fallback(self):
        for task in ('plan','write','direct','grounding','review','critique'):
            fixture=FullFixture()
            def fail(p):
                if p['task']==task:raise ModelError('注入模型失败')
                return fixture(p)
            with self.subTest(task=task):
                result=run(fail)
                self.assertEqual(result['status'],'MODEL_FAILED')
                self.assertIsNone(result['script'])

    def test_runtime_never_uses_template_grounding_in_llm_mode(self):
        with patch('src.grounding.template_drafts',side_effect=AssertionError('不能调用模板白名单')):
            self.assertEqual(run()['status'],'COMPLETED')

    def test_generated_claim_is_repaired_even_when_user_default_is_locked(self):
        fixture=FullFixture()
        def inject(p):
            r=fixture(p)
            if p['task']=='write':r['beats'][0]['voiceover']='这只杯子仅重200克。'
            return r
        result=run(inject)
        self.assertEqual(result['status'],'COMPLETED')
        self.assertIn('REPAIR_UNVERIFIED',[e['action'] for e in result['trace']])
        self.assertEqual([p['task'] for p in fixture.seen].count('grounding'),2)
        self.assertNotIn('200克',str(result['script']))

    def test_semantic_audit_may_not_omit_duplicate_or_fabricate_quotes(self):
        for defect in ('omit','duplicate','fake_quote','missing_citation','alter_text'):
            fixture=FullFixture()
            def inject(p):
                r=fixture(p)
                if p['task']=='grounding':
                    if defect=='omit':r['records'].pop()
                    elif defect=='duplicate':r['records'][-1]=r['records'][0]
                    elif defect=='alter_text':r['records'][0]['text']='假的原文'
                    else:
                        r['records'][0].update(verdict='supported',citations=[])
                        if defect=='fake_quote':r['records'][0]['citations']=[{'material_id':'D01','source_field':'fact','quote':'仅重200克'}]
                return r
            with self.subTest(defect=defect):self.assertEqual(run(inject)['status'],'MODEL_FAILED')

    def test_director_cannot_change_beat_or_omit_scene(self):
        for defect in ('omit','rewrite'):
            fixture=FullFixture()
            def inject(p):
                r=fixture(p)
                if p['task']=='direct':
                    if defect=='omit':r['scenes'].pop()
                    else:r['scenes'][0]['voiceover']='导演擅改文案'
                return r
            with self.subTest(defect=defect):self.assertEqual(run(inject)['status'],'MODEL_FAILED')

    def test_short_only_compresses_after_actual_overrun_and_rechecks(self):
        fixture=FullFixture()
        result=run(fixture,{**request().fields,'target_seconds':15})
        self.assertEqual(result['status'],'COMPLETED')
        directs=[p for p in fixture.seen if p['task']=='direct']
        self.assertEqual([p['compact'] for p in directs],[False,True])
        self.assertLessEqual(result['script']['estimated_seconds'],15)
        self.assertEqual([p['task'] for p in fixture.seen].count('grounding'),2)
        normal=FullFixture();self.assertEqual(run(normal)['status'],'COMPLETED')
        self.assertEqual([p['compact'] for p in normal.seen if p['task']=='direct'],[False])

    def test_director_cannot_lower_action_floor_to_fake_fit(self):
        fixture=FullFixture()
        def inject(p):
            r=fixture(p)
            if p['task']=='direct' and p['compact']:r['scenes'][0]['minimum_visual_seconds']=1
            return r
        result=run(inject,{**request().fields,'target_seconds':15})
        self.assertEqual(result['status'],'MODEL_FAILED')

    def test_creative_reviewer_feedback_drives_model_rewrite(self):
        fixture=FullFixture(); count=0
        def inject(p):
            nonlocal count
            r=fixture(p)
            if p['task']=='critique':
                count+=1
                if count==1:
                    b=p['draft']['beats'][1]
                    r.update(passed=False,issues=[{'scene_id':b['id'],'field':'action','code':'CAUSAL_GAP',
                       'evidence':b['action'],'revision_goal':'人物转身的原因不明确，承接开场动作。','preserve':['产品事实与CTA']}])
            return r
        result=run(inject)
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(count,2)
        self.assertIn('rewrite',[p['task'] for p in fixture.seen])
        self.assertEqual(result['creative']['revision_count'],1)

    def test_novel_title_is_preserved_and_audited(self):
        result=run()
        self.assertEqual(result['script']['title'],'早餐带了，这个呢？')
        self.assertEqual(result['script']['title_provenance'][0]['status'],'FICTIONAL')

    def test_supported_paraphrase_gets_original_quote_without_template_match(self):
        fixture=FullFixture()
        line='这个杯盖有个能滑动的锁扣。'
        def inject(p):
            r=fixture(p)
            if p['task']=='write':r['beats'][0]['voiceover']=line
            if p['task']=='grounding':
                for row in r['records']:
                    if row['text']==line:
                        row.update(verdict='supported',citations=[{'material_id':'D01','source_field':'fact','quote':'杯盖带滑动锁扣'}])
            return r
        result=run(inject)
        self.assertEqual(result['status'],'COMPLETED')
        hook=result['script']['scenes'][0]
        self.assertEqual(hook['voiceover'],line)
        self.assertEqual(hook['material_ids'],['D01'])
        self.assertEqual(next(r for r in hook['field_provenance'] if r['field']=='voiceover')['status'],'MODEL_REVIEWED')

    def test_locked_unsupported_user_copy_is_not_silently_rewritten(self):
        result=run(fields={**request().fields,'hook_line':'这只杯子仅重200克。'})
        self.assertEqual(result['status'],'NEEDS_REVIEW')
        self.assertNotIn('REPAIR_UNVERIFIED',[e['action'] for e in result['trace']])

    def test_malformed_semantic_verdict_does_not_crash_process(self):
        fixture=FullFixture()
        def inject(p):
            r=fixture(p)
            if p['task']=='grounding':r['records'][0]['verdict']=[]
            return r
        self.assertEqual(run(inject)['status'],'MODEL_FAILED')

    def test_reused_client_resets_job_context_and_call_accounting(self):
        i=request(); fixture=FullFixture(); models=RemoteStudio(fixture)
        studio=Studio(models,LocalTools(i.materials,()))
        first=studio.run(i.fields); second=studio.run(i.fields)
        self.assertEqual(first['status'],second['status'])
        self.assertEqual(first['audit']['model_calls'],second['audit']['model_calls'])
        self.assertEqual(len(models.model_calls),second['audit']['model_calls'])
        self.assertTrue(all(not p['previous_scenes'] for p in fixture.seen if p['task']=='direct'))
