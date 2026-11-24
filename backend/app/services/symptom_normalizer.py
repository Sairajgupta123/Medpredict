"""Conservative symptom phrase normalization for MediPredict.

This module maps explicitly curated phrases to vocabulary identifiers. It is not a clinical NLP
system: it cannot reliably resolve negation, time, uncertainty, severity, or conversational scope.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "symptom_taxonomy.json"
MAX_INPUT_CHARACTERS = 4_000
NEGATION_CUES = {
    "no", "not", "without", "denies", "denied", "deny",
    "do not have", "does not have", "did not have", "don't have",
    "doesn't have", "didn't have", "dont have", "doesnt have",
    "do not have a", "does not have a", "did not have a",
    "dont have a", "doesnt have a", "didnt have a",
}
HISTORICAL_CUES = {
    "previously", "earlier", "last week", "last month", "yesterday",
    "used to have", "had", "had a",
}
UNCERTAINTY_CUES = {
    "maybe", "might have", "may have", "possibly", "perhaps",
    "think i have", "think i might have", "not sure if",
}


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
    value = re.sub(r"[^\w']+", " ", value, flags=re.UNICODE)
    return " ".join(value.split()).replace("'", "")


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> tuple[Symptom, ...]:
    """Load and validate the versioned symptom vocabulary."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("taxonomy_version")
    status = payload.get("status")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Taxonomy must declare a semantic taxonomy_version")
    if not isinstance(status, str) or not status.strip():
        raise ValueError("Taxonomy must declare its governance status")
    if not isinstance(payload.get("language"), str) or not payload["language"].strip():
        raise ValueError("Taxonomy must declare its language")
    if not isinstance(payload.get("normalization_policy"), dict):
        raise ValueError("Taxonomy must declare a normalization_policy")
    entries = payload.get("symptoms")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Taxonomy symptoms must be a non-empty list")

    symptoms: list[Symptom] = []
    seen_ids: set[str] = set()
    seen_aliases: dict[str, str] = {}

    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Every taxonomy symptom must be an object")
        for field in ("id", "label", "category", "aliases"):
            if field not in item:
                raise ValueError(f"Taxonomy symptom is missing required field: {field}")
        if not all(isinstance(item[field], str) and item[field].strip() for field in ("id", "label", "category")):
            raise ValueError("Symptom id, label and category must be non-empty strings")
        if not isinstance(item["aliases"], list) or not all(
            isinstance(alias, str) for alias in item["aliases"]
        ):
            raise ValueError(f"Symptom {item['id']} aliases must be a string list")
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
            normalized_alias = normalize_phrase(alias)
            if not normalized_alias:
                raise ValueError(f"Symptom {symptom.id} has an empty alias")
            existing = seen_aliases.get(normalized_alias)
            if existing and existing != symptom.id:
                raise ValueError(
                    f"Alias collision for normalized phrase: {normalized_alias!r}"
                )
            seen_aliases[normalized_alias] = symptom.id
        symptoms.append(symptom)

    if not symptoms:
        raise ValueError("Taxonomy contains no symptoms")
    return tuple(symptoms)


def _taxonomy_version(path: Path = DEFAULT_TAXONOMY_PATH) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload["taxonomy_version"])


def _mention_context(normalized_text: str, start: int) -> str:
    """Return a bounded prefix window for conservative cue detection."""
    prefix = normalized_text[:start].split()
    return " ".join(prefix[-8:])


def _scope_status(normalized_text: str, start: int) -> str:
    """Flag a small set of nearby scope cues; this is not reliable clinical NLP."""
    context = _mention_context(normalized_text, start)

    # Uncertainty takes precedence in phrases such as "I am not sure if I have fever".
    if any(cue in context for cue in UNCERTAINTY_CUES):
        return "uncertain_context"

    negation_patterns = (
        r"\bno$",
        r"\bwithout$",
        r"\b(?:deny|denies|denied)$",
        r"\bnot$",
        r"\bnot\s+(?:have|having)(?:\s+(?:any|a|an))?$",
        r"\b(?:am|is|are|was|were)\s+not"
        r"(?:\s+(?:have|having))?(?:\s+(?:any|a|an))?$",
        r"\b(?:do not|does not|did not|dont|doesnt|didnt)\s+"
        r"(?:have)?(?:\s+(?:any|a|an))?$",
    )
    if any(re.search(pattern, context) for pattern in negation_patterns):
        return "negated_or_denied_context"

    historical_patterns = (
        r"\b(?:previously|earlier|yesterday|last week|last month)$",
        r"\b(?:used to have|had|had a|had an)$",
    )
    if any(re.search(pattern, context) for pattern in historical_patterns):
        return "possibly_historical_context"

    return "explicit_mention_unresolved"


def normalize_symptoms(
    text: str,
    taxonomy: tuple[Symptom, ...] | None = None,
) -> dict[str, Any]:
    """Extract curated phrases and flag obvious contextual cues for human review."""
    if not isinstance(text, str):
        raise TypeError("Symptom input must be a string")
    if len(text) > MAX_INPUT_CHARACTERS:
        raise ValueError(f"Symptom input exceeds {MAX_INPUT_CHARACTERS} characters")

    normalized = normalize_phrase(text)
    if not normalized:
        return {
            "taxonomy_version": _taxonomy_version() if taxonomy is None else "custom",
            "matched_symptoms": [],
            "contextual_mentions": [],
            "unrecognized_text_present": False,
            "review_required": True,
            "reason": "empty_input",
            "clinical_interpretation_performed": False,
        }

    symptoms = taxonomy if taxonomy is not None else load_taxonomy()
    padded_text = f" {normalized} "
    candidates: list[tuple[int, int, Symptom]] = []

    for symptom in symptoms:
        for alias in symptom.aliases:
            phrase = normalize_phrase(alias)
            needle = f" {phrase} "
            start = padded_text.find(needle)
            while start >= 0:
                candidates.append((start, len(needle), symptom))
                start = padded_text.find(needle, start + 1)

    accepted_spans: list[tuple[int, int]] = []
    accepted: dict[str, tuple[Symptom, str]] = {}
    for start, width, symptom in sorted(
        candidates, key=lambda candidate: (-candidate[1], candidate[0])
    ):
        end = start + width
        if any(start < other_end and other_start < end for other_start, other_end in accepted_spans):
            continue
        accepted_spans.append((start, end))
        # Subtract the leading padding character before inspecting the original normalized text.
        status = _scope_status(normalized, max(0, start - 1))
        accepted[symptom.id] = (symptom, status)

    matched = []
    contextual = []
    for symptom, status in sorted(
        accepted.values(), key=lambda item: item[0].id
    ):
        item = {
            "id": symptom.id,
            "label": symptom.label,
            "category": symptom.category,
        }
        if status == "explicit_mention_unresolved":
            matched.append(item)
        else:
            contextual.append({**item, "context_flag": status})

    # Remove every recognized phrase, then ignore common grammatical filler.
    # Any remaining token is deliberately surfaced as unsupported text rather
    # than silently treating a partially understood narrative as fully parsed.
    residual_characters = list(padded_text)
    for start, end in accepted_spans:
        for position in range(start, end):
            residual_characters[position] = " "
    residual_tokens = set("".join(residual_characters).split())
    filler_tokens = {
        "i", "me", "my", "we", "you", "he", "she", "they", "it",
        "have", "has", "had", "am", "is", "are", "was", "were",
        "a", "an", "the", "and", "but", "or", "with", "of", "to",
        "for", "in", "on", "at", "some", "any", "please", "experiencing",
        "experience", "feeling", "feel", "been", "being", "there",
        "this", "that", "from", "since",
    }
    unrecognized_text_present = bool(residual_tokens - filler_tokens)

    return {
        "taxonomy_version": _taxonomy_version() if taxonomy is None else "custom",
        "matched_symptoms": matched,
        "contextual_mentions": contextual,
        "unrecognized_text_present": unrecognized_text_present,
        "review_required": True,
        "reason": "explicit_phrase_matches" if matched else (
            "context_requires_review" if contextual else "no_supported_phrase_match"
        ),
        "clinical_interpretation_performed": False,
    }
