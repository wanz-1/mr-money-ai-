# Maintenance Guide

## Routine Checks

Weekly:

- run unit and integration tests
- review extraction failures
- review high-severity security findings
- check backup completion
- check webhook delivery errors
- review dependency and container scan results

Monthly:

- test restore from backup
- review retention policy enforcement
- update approved citation/source adapters
- review AI model evaluation results
- rotate non-user service credentials where policy requires

## AI Evaluation Benchmarks

Maintain benchmark sets for:

- grammar correction precision
- citation detection
- unsupported claim detection
- internal similarity detection
- accessibility markup checks
- sensitive-data detection
- AI-writing indicator calibration

Benchmark results should include false positives, false negatives, and reviewer notes.

## Change Management

For every release:

- document migration impact
- keep rollback instructions
- record model and prompt versions
- store evaluation results
- update user-facing limitations when capabilities change

## Backup and Restore

Production deployments should back up:

- relational database
- encrypted object storage metadata
- generated reports where retained
- audit logs
- configuration and policy state

Restore tests must verify document metadata, access controls, review reports, and audit log continuity.

