"""Privacy-conscious first-pass audit for a local symptom dataset CSV.

The report contains aggregate statistics only. It deliberately does not print or export
individual symptom text, identifiers, or raw rows.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


def normalize_text(series: pd.Series) -> pd.Series:
    """Normalize whitespace and casing for duplicate diagnostics."""
    return (
        series.fillna("")
        .astype(str)
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def audit_dataset(
    path: Path,
    text_column: str,
    label_column: str,
    group_column: str | None = None,
) -> dict[str, Any]:
    """Return aggregate quality metrics without exposing source text."""
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file does not exist: {path}")

    frame = pd.read_csv(path)
    required = {text_column, label_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    if group_column and group_column not in frame.columns:
        raise ValueError(f"Group column does not exist: {group_column}")

    raw_rows = len(frame)
    text = normalize_text(frame[text_column])
    labels = normalize_text(frame[label_column])
    usable = text.ne("") & labels.ne("")
    clean_text = text[usable]
    clean_labels = labels[usable]
    clean = frame.loc[usable].copy()

    if clean.empty:
        raise ValueError("No usable rows remain after blank text/label removal.")

    label_counts = clean_labels.value_counts()
    pair_frame = pd.DataFrame({"text": clean_text, "label": clean_labels})
    exact_pair_duplicates = int(pair_frame.duplicated().sum())
    text_duplicate_rows = int(clean_text.duplicated().sum())

    lengths = clean_text.str.len()
    word_counts = clean_text.str.split().str.len()

    result: dict[str, Any] = {
        "source_file_name": path.name,
        "raw_row_count": int(raw_rows),
        "usable_row_count": int(len(clean)),
        "dropped_blank_text_or_label_rows": int(raw_rows - len(clean)),
        "class_count": int(label_counts.size),
        "class_count_distribution": {
            str(label): int(count) for label, count in label_counts.items()
        },
        "smallest_class_size": int(label_counts.min()),
        "largest_class_size": int(label_counts.max()),
        "class_imbalance_ratio_max_to_min": float(label_counts.max() / label_counts.min()),
        "normalized_duplicate_text_rows": text_duplicate_rows,
        "normalized_duplicate_text_label_pair_rows": exact_pair_duplicates,
        "text_character_length": {
            "min": int(lengths.min()),
            "median": float(lengths.median()),
            "p95": float(lengths.quantile(0.95)),
            "max": int(lengths.max()),
        },
        "text_word_count": {
            "min": int(word_counts.min()),
            "median": float(word_counts.median()),
            "p95": float(word_counts.quantile(0.95)),
            "max": int(word_counts.max()),
        },
        "group_audit": None,
        "warnings": [],
    }

    if group_column:
        groups = normalize_text(clean[group_column])
        blank_groups = int(groups.eq("").sum())
        result["group_audit"] = {
            "group_column": group_column,
            "blank_group_rows": blank_groups,
            "unique_group_count": int(groups[groups.ne("")].nunique()),
            "group_ids_are_not_exported": True,
        }
        if blank_groups:
            result["warnings"].append(
                "Blank group identifiers exist; do not use group-aware evaluation until resolved."
            )
        if groups[groups.ne("")].nunique() < 2:
            result["warnings"].append(
                "Fewer than two non-blank groups exist; group-aware holdout is not possible."
            )
    else:
        result["warnings"].append(
            "No group column supplied. Patient/source leakage cannot be ruled out."
        )

    if result["class_imbalance_ratio_max_to_min"] > 5:
        result["warnings"].append(
            "Largest class is more than five times the smallest; inspect imbalance and per-class recall."
        )
    if text_duplicate_rows:
        result["warnings"].append(
            "Repeated normalized text exists; inspect duplicates and split leakage before training."
        )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--text-column", default="symptom_text")
    parser.add_argument("--label-column", default="condition_label")
    parser.add_argument("--group-column", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = audit_dataset(
        args.data,
        args.text_column,
        args.label_column,
        args.group_column,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
