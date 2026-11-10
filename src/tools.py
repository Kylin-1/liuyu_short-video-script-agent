"""Deterministic business tools. Media inputs are textual fixtures."""
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict

from .claims import MEASURABLE, clean, unsupported_clauses
from .schema import Beat, Draft, Material, Scene

TOOL_NAMES = ("search_material", "estimate_duration", "check_brand")
TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z]|\d|[%℃]|[.。！？!?，,、；;：:]")
PAUSE = frozenset(".。！？!?，,、；;：:")


class ToolError(RuntimeError):
    pass


def normalized(text: str) -> str:
    return clean(text)


def read_units(text: str) -> float:
    # Each digit or Latin letter gets one unit. Decimal points and % add units.
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=\d)\.(?=\d)", "点", text)
    return sum(0.45 if token in PAUSE else 2 if token in "%℃" else 1
               for token in TOKEN.findall(text))


def text_seconds(beat: Beat, speech_rate: float = 4.0, reading_rate: float = 6.0) -> tuple[int, int]:
    spoken = math.ceil(read_units(beat.voiceover) / speech_rate)
    reading = 0 if beat.subtitle == beat.voiceover else math.ceil(read_units(beat.subtitle) / reading_rate)
    return spoken, reading


class LocalTools:
    def __init__(self, materials: tuple[Material, ...], banned: tuple[str, ...],
                 fault: str = "", fault_times: int = 0, required: tuple[str, ...] = ()):
        self.materials = materials
        self.banned = banned
        self.required = required
        self.fault = fault
        self.fault_times = fault_times
        self.attempts = Counter()

    def _check_fault(self, name: str) -> None:
        self.attempts[name] += 1
        if name == self.fault and self.attempts[name] <= self.fault_times:
            raise ToolError("模拟工具不可用")

    def search_material(self, subject: str, query: str, material_id: str = "") -> tuple[Material, ...]:
        self._check_fault("search_material")
        key, hint = normalized(subject), normalized(query)
        matches = []
        for item in self.materials:
            if material_id and item.id != material_id:
                continue
            if key not in {normalized(alias) for alias in (item.subject, *item.aliases)}:
                continue
            searchable = normalized(" ".join((item.fact, item.visual, item.operation, *item.tags)))
            if not hint or hint in searchable:
                matches.append(item)
        return tuple(matches[:3])

    def estimate_duration(self, scenes: tuple[Scene, ...], target_seconds: int,
                          speech_rate: float = 4.0, reading_rate: float = 6.0) -> dict:
        self._check_fault("estimate_duration")
        estimates = []
        for scene in scenes:
            spoken, reading = text_seconds(scene.beat, speech_rate, reading_rate)
            effective = max(scene.minimum_visual_seconds, scene.planned_seconds, spoken, reading)
            estimates.append({
                "scene_id": scene.beat.id,
                "planned_seconds": scene.planned_seconds,
                "minimum_visual_seconds": scene.minimum_visual_seconds,
                "spoken_seconds": spoken,
                "reading_seconds": reading,
                "estimated_seconds": effective,
            })
        total = sum(row["estimated_seconds"] for row in estimates)
        return {"passed": total <= target_seconds, "target_seconds": target_seconds,
                "total_seconds": total, "over_seconds": max(0, total - target_seconds),
                "scenes": estimates}

    def check_brand(self, draft: Draft, scenes: tuple[Scene, ...],
                    materials: tuple[Material, ...]) -> dict:
        self._check_fault("check_brand")
        issues = []
        sources = {item.id: item for item in materials}
        cited_ids = {scene.beat.material_id for scene in scenes}
        title_facts = tuple(item.fact for item in materials if item.id in cited_ids)
        for claim in unsupported_clauses(draft.title, title_facts):
            issues.append({"scene_id": "title", "field": "title", "code": "UNSUPPORTED_CLAIM",
                           "value": claim, "material_ids": sorted(cited_ids - {""})})
        fields = [("title", "title", draft.title)]
        for scene in scenes:
            beat = scene.beat
            source = sources.get(beat.material_id)
            facts = (source.fact,) if source else ()
            for name in ("action", "voiceover", "subtitle"):
                value = getattr(beat, name)
                fields.append((beat.id, name, value))
                unsupported = unsupported_clauses(value, facts)
                # The retrieved footage description can establish what is shown, but does not
                # substantiate marketing figures absent from its fact record.
                if name == "action" and source and value in {source.visual, source.operation}:
                    unsupported = [claim for claim in unsupported
                                   if not self._numeric_footage_matches(claim, source.fact)]
                for claim in unsupported:
                    issues.append({"scene_id": beat.id, "field": name, "code": "UNSUPPORTED_CLAIM",
                                   "value": claim, "material_ids": [source.id] if source else []})
            if beat.material_id and beat.material_id not in sources:
                issues.append({"scene_id": beat.id, "field": "material_id",
                               "code": "UNKNOWN_SOURCE", "value": beat.material_id})
        for scene_id, field, value in fields:
            for term in self.banned:
                if normalized(term) in normalized(value):
                    issues.append({"scene_id": scene_id, "field": field,
                                   "code": "BANNED_TERM", "value": term})
        on_screen_or_spoken = [normalized(value) for _, field, value in fields
                              if field in {"voiceover", "subtitle"}]
        for term in self.required:
            if not any(normalized(term) in value for value in on_screen_or_spoken):
                issues.append({"scene_id": "", "field": "voiceover/subtitle",
                               "code": "REQUIRED_TERM_MISSING", "value": term})
        return {"passed": not issues, "issues": issues}

    @staticmethod
    def _numeric_footage_matches(visual_claim: str, fact: str) -> bool:
        visual = clean(visual_claim)
        approved = clean(fact)
        # This is narrowly for a receipt or on-screen proof of the same advertised discount.
        receipt = re.fullmatch(r"(?:小票|收银屏|券码页)显示(.+)", visual)
        if not receipt or not MEASURABLE.search(receipt[1]):
            return False
        wording = receipt[1].replace("立减", "减")
        return wording in approved.replace("立减", "减")


def material_summary(items: tuple[Material, ...]) -> list[dict]:
    return [asdict(item) for item in items]
