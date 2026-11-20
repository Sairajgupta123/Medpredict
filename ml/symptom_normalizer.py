"""Conservative symptom phrase normalization for MediPredict.

This module maps explicitly listed phrases to vocabulary identifiers. It does not infer
conditions, negate symptoms, assess severity, triage emergencies, or interpret clinical context.
Unrecognized text is never echoed in the returned result.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TAXONOMY_PATH = Path(__file__).with_name("symptom_taxonomy.json")
MAX_INPUT_CHARACTERS = 4_000


@dataclass(frozen=True)
class Symptom:
    id: str
    label: str
    category: str
    aliases: tuple[str, ...]


def normalize_phrase(value: str) -> str:
    """Normalize a phrase for exact token-boundary matching."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("’", "'")
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> tuple[Symptom, ...]:
    """Load and validate the versioned symptom vocabulary."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    symptoms: list[Symptom] = []
    seen_ids: set[str] = set()
    seen_aliases: dict[str, str] = {}

    for item in payload.get("symptoms", []):
        symptom = Symptom(
            id=str(item["id"]),
            label=str(item["label"]),
            category=str(item["category"]),
            aliases=tuple(str(alias) for alias in item["aliases"]),
        )
        if symptom.id in seen_ids:
            raise ValueError(f"Duplicate symptom identifier: {symptom.id}")
        seen_ids.add(symptom.id)

        if not symptom.aliases:
            raise ValueError(f"Symptom {symptom.id} has no aliases")
        for alias in symptom.aliases:
            normalized = normalize_phrase(alias)
            if not normalized:
                raise ValueError(f"Symptom {symptom.id} has an empty alias")
            existing = seen_aliases.get(normalized)
            if existing and existing != symptom.id:
                raise ValueError(
                    f"Alias collision for normalized phrase: {normalized!r}"
                )
            seen_aliases[normalized] = symptom.id
        symptoms.append(symptom)

    if not symptoms:
        raise ValueError("Taxonomy contains no symptoms")
    return tuple(symptoms)


def normalize_symptoms(
    text: str,
    taxonomy: tuple[Symptom, ...] | None = None,
) -> dict[str, Any]:
    """Extract explicit symptom mentions; do not infer missing or negated concepts."""
    if not isinstance(text, str):
        raise TypeError("Symptom input must be a string")
    if len(text) > MAX_INPUT_CHARACTERS:
        raise ValueError(f"Symptom input exceeds {MAX_INPUT_CHARACTERS} characters")

    normalized = normalize_phrase(text)
    if not normalized:
        return {
            "taxonomy_version": "0.1.0",
            "matched_symptoms": [],
            "unrecognized_text_present": False,
            "review_required": True,
            "reason": "empty_input",
            "clinical_interpretation_performed": False,
        }

    symptoms = taxonomy if taxonomy is not None else load_taxonomy()
    padded_text = f" {normalized} "
    candidates: list[tuple[int, int, Symptom, str]] = []

    for symptom in symptoms:
        for alias in symptom.aliases:
            phrase = normalize_phrase(alias)
            needle = f" {phrase} "
            start = padded_text.find(needle)
            while start >= 0:
                candidates.append((start, len(needle), symptom, phrase))
                start = padded_text.find(needle, start + 1)

    # Longest-first selection prevents a shorter phrase from masking a longer one.
    accepted_spans: list[tuple[int, int]] = []
    accepted: dict[str, Symptom] = {}
    for start, width, symptom, _phrase in sorted(
        candidates, key=lambda candidate: (-candidate[1], candidate[0])
    ):
        end = start + width
        if any(start < other_end and other_start < end for other_start, other_end in accepted_spans):
            continue
        accepted_spans.append((start, end))
        accepted[symptom.id] = symptom

    matched = [
        {
            "id": symptom.id,
            "label": symptom.label,
            "category": symptom.category,
        }
        for symptom in sorted(accepted.values(), key=lambda item: item.id)
    ]

    return {
        "taxonomy_version": "0.1.0",
        "matched_symptoms": matched,
        "unrecognized_text_present": not bool(matched),
        "review_required": True,
        "reason": "explicit_phrase_matches" if matched else "no_supported_phrase_match",
        "clinical_interpretation_performed": False,
    }
