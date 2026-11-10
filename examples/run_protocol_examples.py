"""Exercise every real adapter using a scripted endpoint double, NOT real-model evidence."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from src.intake import normalize,split_text
from src.llm_studio import RemoteStudio
from src.main import atomic_json
from src.studio import Studio
from src.tools import LocalTools
from remote_fixtures import FullFixture


def main():
    i=normalize(split_text((ROOT/'examples/inputs/raw_intent_story.txt').read_text(encoding='utf-8')))
    cases=[]
    for name,seconds,attack in [('normal',30,False),('over_duration',15,False),('unsupported_claim',30,True)]:
        fixture=FullFixture()
        def endpoint(payload):
            response=fixture(payload)
            if attack and payload['task']=='write':response['beats'][0]['voiceover']='这只杯子仅重200克。'
            return response
        result=Studio(RemoteStudio(endpoint,model_name='scripted-protocol-fixture'),LocalTools(i.materials,())).run({**i.fields,'target_seconds':seconds})
        assert result['status']=='COMPLETED',result['detail']
        cases.append({'case':name,'evidence_mode':'scripted_protocol_test','real_model_evidence':False,
                      'role_call_counts':{role:sum(p['task']==role for p in fixture.seen) for role in sorted({p['task'] for p in fixture.seen})},
                      'result':result})
    atomic_json(ROOT/'examples/protocol-results.json',{'evidence_mode':'scripted_protocol_test',
        'note':'全角色适配器协议测试，端点使用预设响应。','cases':cases})
    print('3 protocol paths passed; real_model_evidence=false')

if __name__=='__main__':main()
