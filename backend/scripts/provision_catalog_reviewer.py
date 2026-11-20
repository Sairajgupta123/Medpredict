"""Provision or revoke catalog reviewer access through a controlled operator workflow.

Run from backend/ after applying migrations:
    python scripts/provision_catalog_reviewer.py --email reviewer@example.org \
        --role reviewer --reason "Verified reviewer appointment"

The operator identity must come from the trusted deployment shell environment.
"""

import argparse
import os
import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.user import RoleProvisioningEvent, User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Existing account email")
    parser.add_argument(
        "--role",
        required=True,
        choices=("patient", "reviewer"),
        help="Grant reviewer access or revoke it back to patient",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Operational justification (at least 8 non-whitespace characters)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and display the proposed change without committing it",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    operator = os.environ.get("MEDIPREDICT_ROLE_PROVISIONING_OPERATOR", "").strip()
    email = args.email.strip().lower()
    reason = args.reason.strip()

    if len(operator) < 3:
        print(
            "Set MEDIPREDICT_ROLE_PROVISIONING_OPERATOR in the trusted operator shell.",
            file=sys.stderr,
        )
        return 2
    if len(reason) < 8:
        print("Reason must contain at least 8 non-whitespace characters.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print("No account exists for that email.", file=sys.stderr)
            return 1
        if not user.is_active:
            print("Inactive accounts cannot be provisioned.", file=sys.stderr)
            return 1
        if args.role == "reviewer" and not user.email_verified:
            print("Reviewer access requires a verified account email.", file=sys.stderr)
            return 1
        if user.role == args.role:
            print(f"Account already has role '{args.role}'; no change made.")
            return 0

        previous_role = user.role
        print(f"Target account: {user.email}")
        print(f"Role change: {previous_role} -> {args.role}")
        print(f"Operator: {operator}")
        print(f"Reason: {reason}")
        if args.dry_run:
            print("Dry run only; database was not changed.")
            return 0

        confirmation = input("Type the target email exactly to confirm: ").strip().lower()
        if confirmation != email:
            print("Confirmation did not match; no change made.", file=sys.stderr)
            return 1

        user.role = args.role
        db.add(
            RoleProvisioningEvent(
                target_user_id=user.id,
                previous_role=previous_role,
                new_role=args.role,
                operator_identity=operator,
                reason=reason,
            )
        )
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        print(f"Role updated to '{args.role}'. Provisioning event committed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
