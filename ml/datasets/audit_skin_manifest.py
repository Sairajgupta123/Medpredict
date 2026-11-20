"""Aggregate-only audit for skin-image dataset manifests.

Expected CSV columns:
- image_id: non-identifying image key
- image_path: path relative to --image-root
- label: dataset-provided class label
Optional:
- lesion_id: non-identifying lesion grouping key
- patient_id: pseudonymous patient grouping key

The report deliberately excludes raw identifiers and paths. This is a research intake tool,
not a clinical validation or license review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image, UnidentifiedImageError


REQUIRED_COLUMNS = {"image_id", "image_path", "label"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}


def _safe_group_summary(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    values = frame[column].fillna("").astype(str).str.strip()
    nonblank = values[values.ne("")]
    return {
        "blank_rows": int(values.eq("").sum()),
        "unique_groups": int(nonblank.nunique()),
    }


def audit_skin_manifest(
    manifest_path: Path,
    image_root: Path,
    inspect_images: bool = True,
) -> dict[str, Any]:
    """Audit metadata, grouping, file availability, decoding and duplicate content."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest does not exist: {manifest_path}")
    if not image_root.is_dir():
        raise NotADirectoryError(f"Image root does not exist: {image_root}")

    frame = pd.read_csv(manifest_path)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Manifest is missing required columns: {sorted(missing)}")

    frame = frame.copy()
    for column in ("image_id", "image_path", "label"):
        frame[column] = frame[column].fillna("").astype(str).str.strip()

    report: dict[str, Any] = {
        "manifest_file_name": manifest_path.name,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "blank_image_id_rows": int(frame["image_id"].eq("").sum()),
        "blank_image_path_rows": int(frame["image_path"].eq("").sum()),
        "blank_label_rows": int(frame["label"].eq("").sum()),
        "duplicate_image_id_rows": int(frame["image_id"].duplicated().sum()),
        "duplicate_path_rows": int(frame["image_path"].duplicated().sum()),
        "class_counts": {
            str(label): int(count)
            for label, count in frame.loc[frame["label"].ne(""), "label"]
            .value_counts().items()
        },
        "class_count": int(frame.loc[frame["label"].ne(""), "label"].nunique()),
    }

    for group_column in ("patient_id", "lesion_id"):
        if group_column in frame.columns:
            report[group_column] = _safe_group_summary(frame, group_column)
            group_values = frame[group_column].fillna("").astype(str).str.strip()
            valid = frame[group_values.ne("") & frame["label"].ne("")].copy()
            valid["_group"] = valid[group_column].fillna("").astype(str).str.strip().values
            labels_per_group = valid.groupby("_group")["label"].nunique()
            report[group_column]["groups_with_multiple_labels"] = int(
                (labels_per_group > 1).sum()
            )
            report[group_column]["unique_groups_per_class"] = {
                str(label): int(
                    valid.loc[valid["label"].eq(label), "_group"].nunique()
                )
                for label in sorted(valid["label"].unique())
            }

    missing_files = 0
    unsafe_paths = 0
    decode_failures = 0
    unsupported_formats = 0
    zero_dimension_images = 0
    image_hashes: dict[str, list[tuple[int, str]]] = defaultdict(list)

    root = image_root.resolve()
    for index, row in frame.iterrows():
        relative = row["image_path"]
        if not relative:
            missing_files += 1
            continue

        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            unsafe_paths += 1
            continue
        if not candidate.is_file():
            missing_files += 1
            continue

        if not inspect_images:
            continue

        try:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            image_hashes[digest].append((int(index), row["label"]))
            with Image.open(candidate) as image:
                image_format = image.format
                width, height = image.size
                image.verify()
            if image_format not in ALLOWED_FORMATS:
                unsupported_formats += 1
            if width <= 0 or height <= 0:
                zero_dimension_images += 1
        except (OSError, UnidentifiedImageError, ValueError):
            decode_failures += 1

    report["file_integrity"] = {
        "missing_files": missing_files,
        "unsafe_paths_rejected": unsafe_paths,
        "decode_failures": decode_failures,
        "unsupported_formats": unsupported_formats,
        "zero_dimension_images": zero_dimension_images,
        "inspection_performed": bool(inspect_images),
    }

    duplicate_groups = [rows for rows in image_hashes.values() if len(rows) > 1]
    conflicting_duplicate_groups = [
        rows for rows in duplicate_groups
        if len({label for _, label in rows}) > 1
    ]
    report["content_duplicates"] = {
        "duplicate_content_groups": len(duplicate_groups),
        "rows_in_duplicate_content_groups": sum(len(rows) for rows in duplicate_groups),
        "duplicate_groups_with_conflicting_labels": len(conflicting_duplicate_groups),
    }

    # Training readiness is deliberately stricter than a successful file audit.
    blockers: list[str] = []
    if "patient_id" not in frame.columns:
        blockers.append("patient_id_column_missing")
        patient_support: dict[str, int] = {}
    else:
        patient_values = frame["patient_id"].fillna("").astype(str).str.strip()
        if patient_values.eq("").any():
            blockers.append("patient_id_values_missing")
        valid_patients = frame.loc[
            patient_values.ne("") & frame["label"].ne("")
        ].copy()
        patient_support = {
            str(label): int(
                valid_patients.loc[valid_patients["label"].eq(label), "patient_id"]
                .fillna("").astype(str).str.strip().nunique()
            )
            for label in sorted(valid_patients["label"].unique())
        }
        low_support = [
            label for label, count in patient_support.items() if count < 3
        ]
        if low_support:
            blockers.append("one_or_more_classes_have_fewer_than_three_patients")

    if frame["image_id"].eq("").any():
        blockers.append("image_id_values_missing")
    if frame["image_id"].duplicated().any():
        blockers.append("duplicate_image_ids")
    if frame["image_path"].eq("").any():
        blockers.append("image_paths_missing")
    if frame["label"].eq("").any():
        blockers.append("labels_missing")
    if report["content_duplicates"]["duplicate_content_groups"]:
        blockers.append("duplicate_image_content_may_cause_data_leakage")
    if report["content_duplicates"]["duplicate_groups_with_conflicting_labels"]:
        blockers.append("duplicate_image_content_has_conflicting_labels")
    if not inspect_images:
        blockers.append("image_integrity_inspection_not_performed")
    else:
        integrity = report["file_integrity"]
        if integrity["missing_files"]:
            blockers.append("image_files_missing_or_unsafe")
        if integrity["decode_failures"]:
            blockers.append("image_decode_failures")
        if integrity["unsupported_formats"]:
            blockers.append("unsupported_image_formats")
        if integrity["zero_dimension_images"]:
            blockers.append("invalid_image_dimensions")

    report["training_readiness"] = {
        "ready_for_reviewer_signoff": len(blockers) == 0,
        "automatic_training_approval": False,
        "blocking_reasons": blockers,
        "distinct_patients_per_class": patient_support,
        "minimum_patients_per_class": 3,
        "notice": (
            "Passing this technical audit does not approve dataset licensing, privacy, "
            "clinical labels, representativeness, or use in a medical product. Human review "
            "and source-specific permission checks remain mandatory."
        ),
    }

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Skip image decoding and file-content hashing",
    )
    args = parser.parse_args()

    report = audit_skin_manifest(
        args.manifest,
        args.image_root,
        inspect_images=not args.metadata_only,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Aggregate skin dataset audit written to {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
