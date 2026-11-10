"""Opt-in provider acceptance. Never substitutes fixtures when configuration is missing."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.main import atomic_json


def main():
    parser = argparse.ArgumentParser(description='真实模型验收：需自行配置 .env.example 中的变量，文件不会自动加载')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'examples/live')
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    missing = [name for name in ('STUDIO_LLM_URL', 'STUDIO_LLM_MODEL') if not os.environ.get(name)]
    if missing:
        atomic_json(directory / 'acceptance.json', {'status':'BLOCKED', 'reason':'模型配置未提供',
                    'missing_variables':missing, 'model_calls':0, 'real_model_evidence':False})
        print('BLOCKED：未配置模型；只记录阻塞，不生成模型运行记录。')
        return 2
    cases = [('normal', 'raw_intent_story.txt', [], {'COMPLETED'}),
             ('short', 'campaign_short.txt', [], {'COMPLETED','DURATION_UNMET'}),
             ('no_material', 'raw_intent_story.txt', ['--materials','examples/inputs/empty_catalog.json'], {'MATERIAL_REQUIRED'}),
             ('tool_failure', 'raw_intent_story.txt', ['--fail-tool','search_material','--fail-times','2'], {'TOOL_FAILED'})]
    rows=[]
    for name, filename, extra, expected in cases:
        trace_path = directory / f'{name}.trace.json'
        cmd=[sys.executable,'-X','utf8','-m','src.main',f'examples/inputs/{filename}',
             '--model','llm','--json','--trace',str(trace_path),*extra]
        try:
            process=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=500)
            result=json.loads(process.stdout)
            atomic_json(directory / f'{name}.output.json',result)
            trace=json.loads(trace_path.read_text(encoding='utf-8'))
            steps=trace['steps']
            loops=[(e,steps[i+1]) for i,e in enumerate(steps[:-1]) if e.get('calls')]
            observed=bool(loops) and all(a.get('decision_source')==b.get('decision_source')=='llm' for a,b in loops)
            status_ok=result['status'] in expected
            role_calls=[c['role'] for step in steps for c in step.get('model_calls',[])]
            specialists_ok=(name not in {'normal','short'} or result['status']!='COMPLETED' or
                (result.get('creative_model_mode')=='llm' and {'plan','write','direct','grounding','review','critique'} <= set(role_calls)))
            all_model=bool(steps) and all(e.get('decision_source')=='llm' for e in steps)
            # Passing hard gates alone does not mean the model observed a
            # repaired version. Require a decision after a failed CHECK.
            duration_path=True
            if name=='short':
                failed=[i for i,e in enumerate(steps) if any(c['tool']=='estimate_duration' and
                        c.get('result',{}).get('passed') is False for c in e.get('calls',[]))]
                duration_path=bool(failed) and all(i+1<len(steps) for i in failed)
                if result['status']=='COMPLETED':
                    duration_path=duration_path and result['script_version']>1 and steps[-1]['action']=='DELIVER'
            rows.append({'case':name,'status':result['status'],'tool_observation_loop':observed,
                         'all_decisions_from_endpoint':all_model,'duration_repair_or_failure':duration_path,
                         'passed':status_ok and all_model and observed and duration_path and specialists_ok,
                         'role_calls':role_calls, 'specialists_called':specialists_ok,
                         'model':result.get('decision_model'), 'trace':trace_path.name})
        except (subprocess.TimeoutExpired,ValueError,OSError,KeyError,TypeError):
            rows.append({'case':name,'status':'RUN_FAILED','passed':False})
    passed=all(row['passed'] for row in rows)
    atomic_json(directory/'acceptance.json', {'status':'PASSED' if passed else 'FAILED',
        'evidence_mode':'configured_endpoint', 'provider_model':os.environ['STUDIO_LLM_MODEL'],
        'note':'制片人、编剧、导演、事实审核与创作评审均调用所配置端点；提交者须确认端点为真实模型而非预设服务。',
        'cases':rows})
    print('PASSED' if passed else 'FAILED')
    return 0 if passed else 2


if __name__=='__main__':
    raise SystemExit(main())
