"""Scripted protocol doubles. Never label these responses as real LLM evidence."""
import json
from dataclasses import asdict, replace
from copy import deepcopy
from src.models import MockModels
from src.schema import Brief, Beat, Draft, Material, CreativePlan, CREATIVE_FIELDS
from src.tools import normalized


def choose(payload):
    action=next((a for a in payload['allowed_actions'] if a!='STOP'),'STOP')
    result={'action':action,'reason':'协议测试预设响应，不是真实模型决策'}
    if action=='FIND_MATERIAL':result['query']=payload['action_options'][action].get('query','')
    if action=='SELECT_CONCEPT':result['plan_id']=payload['plans'][0]['id']
    return result


def draft(row):return Draft(row['title'],tuple(Beat(**b) for b in row['beats']))


class FullFixture:
    def __init__(self):self.seen=[]
    def __call__(self,payload):
        return json.loads(json.dumps(self._reply(payload),ensure_ascii=False))
    def _reply(self,payload):
        self.seen.append(deepcopy(payload))
        task=payload['task']
        if task=='producer':return choose(payload)
        brief=Brief(**payload['brief'])
        materials=tuple(Material(**m) for m in payload['materials'])
        mock=MockModels()
        if task=='plan':
            plans=mock.propose_concepts(brief,materials)
            plans=tuple(replace(p,setting='厨房早餐台旁，阿宁把纸袋推到桌边',
                  opening='阿宁提起纸袋，同伴用便签指向桌上的物件。',hook_line='早餐带了，这个呢？',
                  field_origins=tuple((k,'llm_proposal') for k,_ in p.field_origins)) for p in plans)
            if brief.creative_policy=='locked':
                plans=tuple(replace(p,**{k:getattr(brief,k) for k in CREATIVE_FIELDS if getattr(brief,k)}) for p in plans)
            return {'plans':[asdict(p) for p in plans]}
        if task=='write':
            plan=CreativePlan(**payload['plan'])
            value=mock.write_concept(brief,plan,materials)
            return asdict(replace(value,title='早餐带了，这个呢？'))
        if task=='direct':
            value=draft(payload['draft'])
            scenes=mock.director(brief,value,payload['compact'])
            return {'scenes':[{'beat_id':s.beat.id, **{k:v for k,v in asdict(s).items() if k!='beat'}} for s in scenes]}
        if task=='grounding':
            records=[]
            for f in payload['fields']:
                cites=[]
                for m in materials:
                    for kind in (('fact','visual','operation') if f['field']=='action' else ('fact',)):
                        quote=getattr(m,kind)
                        if quote and normalized(f['text'])==normalized(quote):
                            cites=[{'material_id':m.id,'source_field':kind,'quote':quote}];break
                    if cites:break
                verdict='supported' if cites else 'fictional'
                if '200克' in f['text'] or '完全不会漏水' in f['text']:verdict='unsupported'
                records.append({**f,'verdict':verdict,'citations':cites,'reason':'预设审核响应，仅测试契约与分支'})
            return {'records':records}
        if task in ('review','critique'):
            return {'passed':True,'issues':[],'scope':'协议测试','human_review_required':True}
        if task=='shorten':return asdict(mock.revise_copy(draft(payload['draft']),payload['scene_ids']))
        if task=='rewrite':
            value=draft(payload['draft'])
            targets={(i['scene_id'],i['field']) for i in payload['issues']}
            beats=[]
            for b in value.beats:
                changes={field:'早餐带了，这个呢？' if field=='voiceover' else '阿宁回头看了看桌面。'
                         for field in ('action','voiceover','subtitle') if (b.id,field) in targets}
                beats.append(replace(b,**changes))
            return asdict(replace(value,beats=tuple(beats),title='早餐带了，这个呢？' if ('title','title') in targets else value.title))
        raise AssertionError(task)
