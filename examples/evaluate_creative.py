"""Compare actual outputs; optionally prepare unlabeled human review forms."""
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.main import atomic_json

PAIRS = [('商品带货', 'raw_intent_story', 'creative_sales'),
         ('商品展示', 'raw_intent_demo', 'creative_demo'),
         ('到店引流', 'campaign_store', 'creative_store'),
         ('活动推广', 'campaign_event', 'creative_event')]
RUBRIC = {
    'opening': '开场是否建立值得继续看的具体期待',
    'causality': '人物行为与转折是否有可理解的原因',
    'product_fit': '商品事实是否自然参与内容而非突然插入',
    'payoff': '结尾是否回应开场并自然衔接指定行动',
    'shootability': '动作、对白和镜头是否能实际拍摄',
}


def build_pairs():
    runs = ROOT / 'examples/runs'
    return [(name, json.loads((runs / f'{old}.output.json').read_text(encoding='utf-8')),
             json.loads((runs / f'{new}.output.json').read_text(encoding='utf-8')))
            for name, old, new in PAIRS]


def blind_forms(pairs, seed):
    rng = random.Random(seed)
    forms, keys = [], []
    for index, (name, old, new) in enumerate(pairs, 1):
        values = [('legacy', old), ('planned', new)]
        rng.shuffle(values)
        case = {'case_id': f'B{index:02d}', 'scenario': name, 'candidates': []}
        for label, (mode, result) in zip(('A', 'B'), values):
            script = result['script']
            # Omit mode, trace, run ID, generated rationale and automatic verdicts.
            candidate = {'label': label, 'title': script['title'], 'target_seconds': script['target_seconds'],
                         'audience': script['audience'], 'platform': script['platform'],
                         'scenes': [{key: scene[key] for key in ('visual', 'voiceover', 'subtitle')}
                                    for scene in script['scenes']],
                         'scores': dict.fromkeys(RUBRIC), 'evidence_and_notes': ''}
            case['candidates'].append(candidate)
            keys.append({'case_id': case['case_id'], 'label': label, 'mode': mode})
        forms.append(case)
    return {'status': 'UNRATED', 'instructions': '每项1至5分，并引用具体镜头解释；未评不要填分。',
            'rubric': RUBRIC, 'cases': forms}, {'seed': seed, 'mapping': keys}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blind-output', type=Path)
    parser.add_argument('--key-output', type=Path)
    parser.add_argument('--seed', type=int, default=20261109)
    args = parser.parse_args()
    if bool(args.blind_output) != bool(args.key_output):
        parser.error('盲评问卷与答案映射须分别指定路径。')
    pairs = build_pairs()
    if args.blind_output:
        if args.blind_output.resolve() == args.key_output.resolve():
            parser.error('问卷与映射不能写入同一文件。')
        form, key = blind_forms(pairs, args.seed)
        atomic_json(args.blind_output, form)
        atomic_json(args.key_output, key)
        return
    lines = ['# 创作流程对照', '', '运行模式：离线 Mock。对照保持输入、素材和规则一致，比较分镜内容与执行开销。人工评价状态：UNRATED。', '',
             '| 场景 | legacy 状态/时长 | planned 状态/时长 | 工具调用（legacy→planned） | 步骤（legacy→planned） |',
             '| --- | --- | --- | --- | --- |']
    for name, old, new in pairs:
        for result in (old, new):
            assert result['status'] == 'COMPLETED'
            assert all(result['checks'][key]['passed'] for key in ('duration', 'rules_and_claims', 'review'))
        assert old['audit']['input_sha256'] == new['audit']['input_sha256']
        assert old['audit']['materials_sha256'] == new['audit']['materials_sha256']
        assert old['audit']['rules_sha256'] == new['audit']['rules_sha256']
        lines.append(f"| {name} | {old['status']} / {old['script']['estimated_seconds']} 秒 | {new['status']} / {new['script']['estimated_seconds']} 秒 | "
                     f"{old['audit']['tool_calls']}→{new['audit']['tool_calls']} | {old['audit']['steps']}→{new['audit']['steps']} |")
    for (name, old, new), (_, old_id, new_id) in zip(pairs, PAIRS):
        lines.extend(['', f'## {name}', '', f'[legacy 脚本](runs/{old_id}.output.md) · [planned 脚本](runs/{new_id}.output.md)', '',
                      f"legacy 开场：{old['script']['scenes'][0]['voiceover'] or old['script']['scenes'][0]['visual']}", '',
                      f"planned 开场：{new['script']['scenes'][0]['voiceover'] or new['script']['scenes'][0]['visual']}"])
    lines.extend(['', '## 定向改写', '', '[参考需求](inputs/raw_creative_reference.txt) · [成稿](runs/creative_reference.output.md) · [Trace](runs/creative_reference.trace.json)', '',
                  '检查引用、估时、事实和品牌通过后，创作诊断定位泛化开场、动机缺口和收尾未兑现，再定向重写。锁定相同内容时停止。', '',
                  '生成匿名评价表：`python examples/evaluate_creative.py --blind-output review.json --key-output review-key.json`。问卷与版本映射分别保存，评分字段初始为空。'])
    (ROOT / 'examples/creative-comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
