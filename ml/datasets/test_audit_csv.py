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
    assert report["symptom_text"]["unique_nonempty_descriptions"] == 3
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
    assert report["labels"]["largest_to_smallest_class_ratio"] == 2.0


def test_audit_detects_same_text_with_conflicting_labels(tmp_path) -> None:
    path = tmp_path / "conflicts.csv"
    pd.DataFrame(
        {
            "symptom_text": ["Fever and cough", " fever   AND cough ", "rash"],
            "condition_label": ["A", "B", "C"],
        }
    ).to_csv(path, index=False)

    report = audit_dataset(path)
    assert report["label_conflicts"]["unique_texts_with_multiple_labels"] == 1
    assert report["label_conflicts"]["rows_in_conflicting_text_groups"] == 2


def test_audit_reports_groups_linked_to_multiple_labels(tmp_path) -> None:
    path = tmp_path / "groups.csv"
    pd.DataFrame(
        {
            "symptom_text": ["one", "two", "three"],
            "condition_label": ["A", "B", "B"],
            "group_id": ["g1", "g1", "g2"],
        }
    ).to_csv(path, index=False)

    report = audit_dataset(path)
    assert report["grouping"]["groups_associated_with_multiple_labels"] == 1


def test_audit_rejects_missing_file(tmp_path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        audit_dataset(tmp_path / "missing.csv")


def test_audit_detects_contact_patterns_without_echoing_values(tmp_path) -> None:
    path = tmp_path / "contacts.csv"
    pd.DataFrame(
        {
            "symptom_text": [
                "Contact person@example.com",
                "Call +1 555 123 4567",
                "ordinary fever and cough",
            ],
            "condition_label": ["A", "B", "A"],
        }
    ).to_csv(path, index=False)

    report = audit_dataset(path)
    rendered = json.dumps(report)
    assert report["symptom_text"]["possible_email_pattern_rows"] == 1
    assert report["symptom_text"]["possible_phone_pattern_rows"] == 1
    assert "person@example.com" not in rendered
    assert "+1 555 123 4567" not in rendered


def test_audit_rejects_header_only_csv(tmp_path) -> None:
    path = tmp_path / "empty.csv"
    pd.DataFrame(columns=["symptom_text", "condition_label"]).to_csv(
        path, index=False
    )
    import pytest

    with pytest.raises(ValueError, match="no data rows"):
        audit_dataset(path)
