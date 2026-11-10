"""Closed-world provenance gate for every audience-visible field.

Exact evidence and trusted local narrative templates can pass offline. Arbitrary
user/model prose is UNKNOWN, never implicitly factual merely for avoiding a regex.
"""
from dataclasses import replace

from . import creative
from .schema import CREATIVE_FIELDS, Brief, Draft
from .tools import normalized

POLICY_VERSION = 'grounding-v1'
FORMATS = {'demo': '细节演示', 'tutorial': '操作步骤', 'story': '情境短片',
           'sales_story': '情境短片', 'talking_head': '口播说明'}
NEUTRAL_COPY = {'大家好，今天给你介绍一款产品。', '大家好。', '然后展示商品。',
                '然后展示产品。', '开始介绍产品。', '摆拍产品，结束视频。',
                '定格上一镜的结果，在空白安全区叠加引导文字。'}


def safe_brief(brief):
    # The product subject must already match the retrieved catalog. Topic and
    # all user-authored prose are not sources of product facts.
    return replace(brief, **{name: '' for name in CREATIVE_FIELDS}, topic='', objective='',
                   visible_result='', cta='' if not brief.conversion_action else brief.resolved_cta,
                   creative_policy='reference')


def canonical_title(brief):
    return f"{brief.subject or '原创人物故事'}｜{FORMATS[brief.format]}"


def template_drafts(brief, materials):
    """Runtime-owned templates only; do not trust the selected model's plan."""
    from .models import MockModels
    safe = safe_brief(brief)
    values = []
    for plan in creative.propose(safe, materials):
        draft = creative.write(safe, plan, materials)
        values.append(draft)
        values.append(MockModels().revise_copy(draft, tuple(beat.id for beat in draft.beats)))
    # Keep the legacy offline examples usable when they contain no custom prose.
    legacy = MockModels().screenwriter(safe, materials)
    values.extend((legacy, MockModels().revise_copy(legacy, tuple(beat.id for beat in legacy.beats))))
    return values


def inspect(brief, draft, scenes, materials):
    trusted = set()
    for value in template_drafts(brief, materials):
        for beat in value.beats:
            for field in ('action', 'voiceover', 'subtitle'):
                if not beat.material_id:
                    trusted.add((field, normalized(getattr(beat, field))))
    for text in NEUTRAL_COPY:
        trusted.add(('voiceover' if text.startswith('大家好') else 'action', normalized(text)))
    records, issues = [], []
    fields = [('title', 'title', draft.title)]
    fields += [(scene.beat.id, name, getattr(scene.beat, name)) for scene in scenes
               for name in ('action', 'voiceover', 'subtitle')]
    for scene_id, field, text in fields:
        if not text:
            continue
        record = {'scene_id': scene_id, 'field': field, 'text': text,
                  'status': 'UNKNOWN', 'basis': None, 'material_ids': [], 'quotes': []}
        key = normalized(text)
        for item in materials:
            # A visual description establishes an action, never a spoken benefit.
            candidates = [('fact', item.fact)] if field != 'action' else [('visual', item.visual), ('operation', item.operation)]
            for kind, quote in candidates:
                if quote and key == normalized(quote):
                    record.update(status='VERIFIED', basis=f'material.{kind}',
                                  material_ids=[item.id], quotes=[quote])
                    break
            if record['status'] == 'VERIFIED':
                break
        if record['status'] == 'UNKNOWN':
            if field == 'title' and text == canonical_title(brief):
                record.update(status='CONTROLLED', basis='catalog_subject_and_format')
            elif (field, key) in trusted:
                record.update(status='CONTROLLED', basis='runtime_template')
            elif (brief.conversion_action and brief.conversion_destination
                  and field == 'subtitle' and text == brief.resolved_cta):
                record.update(status='CONTROLLED', basis='brief_conversion_route')
        if record['status'] == 'UNKNOWN':
            issues.append({'scene_id': scene_id, 'field': field, 'code': 'UNVERIFIED_CONTENT', 'value': text})
        records.append(record)
    return {'passed': not issues, 'issues': issues, 'records': records, 'policy_version': POLICY_VERSION,
            'scope': '离线来源校验：原文及受控表达匹配；未知表述转入复核。'}


def safe_replacement(brief, draft, materials, issues):
    """Replace only reference fields using a clean plan, never copied user prose."""
    safe = safe_brief(brief)
    plan = creative.propose(safe, materials)[0]
    target = creative.write(safe, plan, materials)
    by_purpose = {beat.purpose: beat for beat in target.beats}
    replacements = {(issue['scene_id'], issue['field']) for issue in issues}
    beats = []
    for beat in draft.beats:
        changes = {}
        for field in ('action', 'voiceover', 'subtitle'):
            if (beat.id, field) not in replacements:
                continue
            if (beat.material_id and beat.purpose != 'cta') or beat.purpose not in by_purpose:
                continue
            changes[field] = getattr(by_purpose[beat.purpose], field)
        beats.append(replace(beat, **changes))
    return replace(draft, beats=tuple(beats))
