# PostgreSQL backup and restore runbook

These scripts are operator-run examples. They do not provision a backup
destination, schedule backups, encrypt files at rest, or prove a backup is
restorable. Prefer managed-database automated backups and point-in-time recovery
for production; use these scripts as an additional export and restore exercise.

## Backup

Install PostgreSQL client tools compatible with the database server. Provide
DATABASE_URL without an inline password and PGPASSFILE through the platform's
secret-file mechanism. The password file must be private to the service account
(PostgreSQL expects mode 0600).

Linux/macOS example:

```bash
install -d -m 700 ./backups
export DATABASE_URL='postgresql://backup_user@db.example.internal:5432/medipredict'
export PGPASSFILE='/run/secrets/medipredict.pgpass'
export BACKUP_DIR='./backups'
export BACKUP_RETENTION_DAYS=14
bash deployment/postgres-backup.sh
```

The backup uses PostgreSQL custom format, writes with restrictive permissions,
publishes the final file only after pg_dump succeeds, and writes a SHA-256
checksum. Retention applies to local files only. Copy backups to a separate,
encrypted, access-controlled storage account and configure lifecycle retention
there; do not commit backups or checksums to Git.

Schedule according to the recovery point objective (RPO). Monitor the job's exit
code, backup age, size, destination upload, and storage capacity. Alert if the
latest successful backup exceeds the approved RPO. Keep encryption keys and
database credentials separate from backup storage.

## Restore drill (destructive to the target)

Restore only into a newly created, isolated, empty database. Never point this
script at the live production database. The script requires an explicit
ALLOW_DATABASE_RESTORE=YES, verifies the checksum, and stops on restore errors;
it does not drop existing objects or attempt an automatic rollback.

```bash
export DATABASE_URL='postgresql://restore_user@isolated-db.example.internal:5432/medipredict_restore'
export PGPASSFILE='/run/secrets/medipredict-restore.pgpass'
export BACKUP_FILE='./backups/medipredict-YYYYMMDDTHHMMSSZ.dump'
export ALLOW_DATABASE_RESTORE=YES
bash deployment/postgres-restore.sh
```

After restore:

1. Run cd backend && alembic current against the restored database.
2. Confirm the revision matches the release being tested.
3. Run health/readiness checks and application smoke tests with synthetic
   accounts and data.
4. Verify expected row counts and critical foreign-key relationships.
5. Record restore duration, backup timestamp, tested revision, operator, and
   any data loss against the RPO/RTO.
6. Repeat on a schedule and after material schema or infrastructure changes.

A checksum detects accidental corruption; it is not an authenticity signature.
Protect backup files with encryption and restricted access, and never include
patient data in tickets, logs, or test reports.
