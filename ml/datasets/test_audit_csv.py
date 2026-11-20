"""Tests for aggregate dataset audit utility."""

import json

import pandas as pd
import pytest

from ml.datasets.audit_csv import audit_dataset


def test_audit_reports_aggregate_quality_without_raw_text(tmp_path) -> None:
    path = tmp_path / "symptoms.csv"
    pd.DataFrame(
        {
            "symptom_text": [
                " Fever   and cough ",
                "fever and cough",
                "rash",
                "headache and nausea",
                "sore throat",
                "joint pain",
            ],
            "condition_label": ["A", "A", "A", "B", "B", "B"],
            "group_id": ["p1", "p2", "p3", "p4", "p5", "p6"],
        }
    ).to_csv(path, index=False)

    report = audit_dataset(path, "symptom_text", "condition_label", "group_id")

    assert report["raw_row_count"] == 6
    assert report["usable_row_count"] == 6
    assert report["class_count"] == 2
    assert report["normalized_duplicate_text_rows"] == 1
    assert report["group_audit"]["unique_group_count"] == 6
    assert "Fever" not in json.dumps(report)


def test_audit_rejects_missing_columns(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame({"text": ["fever"], "label": ["A"]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Missing required columns"):
        audit_dataset(path, "symptom_text", "condition_label")


def test_audit_flags_missing_group_ids(tmp_path) -> None:
    path = tmp_path / "groups.csv"
    pd.DataFrame(
        {
            "symptom_text": ["one", "two", "three", "four"],
            "condition_label": ["A", "A", "B", "B"],
            "group_id": ["g1", "", "g3", "g4"],
        }
    ).to_csv(path, index=False)

    report = audit_dataset(path, "symptom_text", "condition_label", "group_id")
    assert report["group_audit"]["blank_group_rows"] == 1
    assert any("Blank group identifiers" in item for item in report["warnings"])
