"""Tests for aggregate-only dataset audit output."""

import json

import pandas as pd

from ml.datasets.audit_csv import audit_dataset


def test_audit_reports_quality_without_exposing_raw_text(tmp_path) -> None:
    path = tmp_path / "sample.csv"
    pd.DataFrame(
        {
            "symptom_text": [
                "Fever and cough",
                "  fever   and cough ",
                "person@example.com with headache",
                "Call +1 555 123 4567 for details",
            ],
            "condition_label": ["A", "A", "B", "B"],
            "group_id": ["p1", "p1", "p2", "p3"],
        }
    ).to_csv(path, index=False)

    report = audit_dataset(path)
    rendered = json.dumps(report)

    assert report["row_count"] == 4
    assert report["symptom_text"]["normalized_duplicate_rows"] == 1
    assert report["symptom_text"]["possible_email_pattern_rows"] == 1
    assert report["symptom_text"]["possible_phone_pattern_rows"] == 1
    assert report["grouping"]["unique_nonblank_groups"] == 3
    assert "person@example.com" not in rendered
    assert "Fever and cough" not in rendered
    assert "p1" not in rendered


def test_audit_reports_missing_values_and_label_imbalance(tmp_path) -> None:
    path = tmp_path / "missing.csv"
    pd.DataFrame(
        {
            "symptom_text": ["cough", None, "fever"],
            "condition_label": ["A", "A", "B"],
        }
    ).to_csv(path, index=False)

    report = audit_dataset(path)
    assert report["null_counts"]["symptom_text"] == 1
    assert report["labels"]["class_counts"] == {"A": 2, "B": 1}


def test_audit_rejects_missing_file(tmp_path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        audit_dataset(tmp_path / "missing.csv")
