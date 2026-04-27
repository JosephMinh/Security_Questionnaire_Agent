# Backup and Recovery Policy

## Backup Frequency
AcmeCloud performs production backups daily for systems and data stores required to support customer-facing services and core business operations.

## Restore Testing
AcmeCloud performs restore tests at least quarterly to confirm that backup data can be recovered successfully and that recovery procedures remain operational.

## Recovery Objectives
AcmeCloud defines target recovery objectives for backup-dependent production services. The target recovery point objective (RPO) is 24 hours, and the target recovery time objective (RTO) is 8 hours.

## Immutable Backup Scope
AcmeCloud uses immutable backups for critical systems and recovery sets that require additional protection against accidental deletion or destructive change. Immutable backups are not currently enabled for all production systems.
