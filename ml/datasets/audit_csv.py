"""Privacy-conscious CSV dataset audit for MediPredict research intake.

The audit reports aggregate quality information only. It never prints raw symptom text,
identifiers, or group IDs. It is a first-pass review aid, not a license or clinical review.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d .()-]{7,}\d)(?!\w)")


def _normalized_text(values: pd.Series) -> pd.Series:
    """Normalize whitespace and case for duplicate analysis only."""
    return (
        values.fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
    )


def audit_dataset(path: Path) -> dict[str, Any]:
    """Return aggregate data-quality metrics without exposing row content."""
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file does not exist: {path}")

    frame = pd.read_csv(path)
    if frame.empty:
        raise ValueError("Dataset CSV contains no data rows.")
    total_rows = len(frame)
    total_columns = len(frame.columns)

    report: dict[str, Any] = {
        "file_name": path.name,
        "row_count": int(total_rows),
        "column_count": int(total_columns),
        "columns": [
            {"name": str(column), "dtype": str(dtype)}
            for column, dtype in frame.dtypes.items()
        ],
        "exact_duplicate_rows": int(frame.duplicated().sum()),
        "null_counts": {
            str(column): int(count)
            for column, count in frame.isna().sum().items()
        },
        "null_rates": {
            str(column): round(float(rate), 4)
            for column, rate in frame.isna().mean().items()
        },
    }

    text_column = "symptom_text"
    label_column = "condition_label"
    normalized = None
    if text_column in frame.columns:
        text = frame[text_column].fillna("").astype(str).str.strip()
        normalized = _normalized_text(frame[text_column])
        nonblank_normalized = normalized[normalized.ne("")]
        report["symptom_text"] = {
            "empty_rows": int(text.eq("").sum()),
            "normalized_duplicate_rows": int(nonblank_normalized.duplicated().sum()),
            "unique_nonempty_descriptions": int(nonblank_normalized.nunique()),
            "length_characters": {
                "min": int(text.str.len().min()) if total_rows else 0,
                "median": float(text.str.len().median()) if total_rows else 0.0,
                "p95": float(text.str.len().quantile(0.95)) if total_rows else 0.0,
                "max": int(text.str.len().max()) if total_rows else 0,
            },
            "possible_email_pattern_rows": int(text.str.contains(EMAIL_PATTERN).sum()),
            "possible_phone_pattern_rows": int(text.str.contains(PHONE_PATTERN).sum()),
        }

    if label_column in frame.columns:
        labels = frame[label_column].fillna("").astype(str).str.strip()
        counts = labels.value_counts(dropna=False)
        nonblank_counts = labels[labels.ne("")].value_counts()
        smallest = int(nonblank_counts.min()) if not nonblank_counts.empty else 0
        largest = int(nonblank_counts.max()) if not nonblank_counts.empty else 0
        report["labels"] = {
            "class_count": int(labels[labels.ne("")].nunique()),
            "blank_label_rows": int(labels.eq("").sum()),
            "class_counts": {str(label): int(count) for label, count in counts.items()},
            "smallest_class_count": smallest,
            "largest_class_count": largest,
            "largest_to_smallest_class_ratio": (
                round(largest / smallest, 3) if smallest else None
            ),
        }

        if normalized is not None:
            paired = pd.DataFrame(
                {"normalized_text": normalized, "label": labels}
            )
            paired = paired[paired["normalized_text"].ne("")]
            labels_per_text = paired.groupby("normalized_text")["label"].nunique()
            conflicting_texts = labels_per_text[labels_per_text > 1]
            report["label_conflicts"] = {
                "unique_texts_with_multiple_labels": int(len(conflicting_texts)),
                "rows_in_conflicting_text_groups": int(
                    paired["normalized_text"].isin(conflicting_texts.index).sum()
                ),
            }

    if "group_id" in frame.columns:
        groups = frame["group_id"].fillna("").astype(str).str.strip()
        nonblank_groups = groups[groups.ne("")]
        report["grouping"] = {
            "blank_group_rows": int(groups.eq("").sum()),
            "unique_nonblank_groups": int(nonblank_groups.nunique()),
            "groups_per_label": {},
            "groups_associated_with_multiple_labels": None,
        }
        if label_column in frame.columns:
            safe = pd.DataFrame({"group": groups, "label": frame[label_column]})
            report["grouping"]["groups_per_label"] = {
                str(label): int(part.loc[part["group"].ne(""), "group"].nunique())
                for label, part in safe.groupby("label", dropna=False)
            }
            group_labels = safe[safe["group"].ne("")].groupby("group")["label"].nunique()
            report["grouping"]["groups_associated_with_multiple_labels"] = int(
                (group_labels > 1).sum()
            )

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = audit_dataset(args.data)
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\\n", encoding="utf-8")
        print(f"Aggregate audit written to {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
