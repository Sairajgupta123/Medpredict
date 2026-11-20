"""Merge catalog reference audit and password reset migration heads.

Revision ID: 0015_merge_reference_and_reset_heads
Revises: 0014_medical_reference_audit, 0014_password_reset_tokens
Create Date: 2026-11-20
"""

from typing import Sequence, Union


revision: str = "0015_merge_reference_and_reset_heads"
down_revision: Union[str, None] = (
    "0014_medical_reference_audit",
    "0014_password_reset_tokens",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge parallel schema histories without changing database objects."""


def downgrade() -> None:
    """A merge revision has no independent schema operations."""
