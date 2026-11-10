"""Conservative checks for measurable and explicit product claims."""
import re
import unicodedata

CLAUSE = re.compile(r"[，,。！？!?；;\n]")
NUMBER = r"[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万点]+"
MEASURABLE = re.compile(
    rf"(?:{NUMBER})\s*(?:%|元|小时|毫升|[wW]功率|[mM][lL])|百分之(?:{NUMBER})"
    r"|(?:效率|速度|销量|转化率|准确率)(?:提升|提高|翻倍|增加)|(?:绝对|永久|百分百)(?:防漏|保温|有效)"
)
PRODUCT_CAPABILITY = re.compile(
    r"支持|自带|配备|具备|自动(?:生成|识别|剪辑)|防漏|防水|保温|耐摔|耐热|无糖|可机洗|可微波"
)
OFFER_TERMS = re.compile(r"减|折|优惠|券|起")
OFFER_QUALIFIERS = ("周末", "到店", "指定", "限量", "仅限", "起")
SCOPE_QUALIFIERS = ("仅", "需", "须", "专业版", "付费版", "会员", "测试版", "部分", "指定", "实验室")


def clean(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).casefold().split()).strip("「」『』“”\"。")


def unsupported_clauses(text: str, facts: tuple[str, ...]) -> list[str]:
    normalized_facts = tuple(clean(fact) for fact in facts)
    full_text = clean(text)
    issues = []
    for raw in CLAUSE.split(text):
        clause = clean(raw)
        measures = set(MEASURABLE.findall(clause))
        if not (measures or PRODUCT_CAPABILITY.search(clause)):
            continue
        if not any(_supported(clause, full_text, measures, fact) for fact in normalized_facts):
            issues.append(raw.strip())
    return issues


def _supported(clause: str, text: str, measures: set[str], fact: str) -> bool:
    if clause not in fact or measures - set(MEASURABLE.findall(fact)):
        return False
    if any(prefix + clause in fact for prefix in ("不", "无", "未", "禁止")):
        return False
    # Do not turn a restricted feature into a promise for every product/customer.
    # Conservative lexical gate: ambiguous paraphrases need review, not guessing.
    if any(term in fact and term not in text for term in SCOPE_QUALIFIERS):
        return False
    if any(term in fact and any(prefix + term in text and prefix + term not in fact
                               for prefix in ("不", "无", "非", "免"))
           for term in SCOPE_QUALIFIERS):
        return False
    if measures and OFFER_TERMS.search(fact):
        return all(term not in fact or term in text for term in OFFER_QUALIFIERS)
    return True
