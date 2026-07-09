# Deployment Guide

## Local Development

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1
```

Open `http://127.0.0.1:8765`.

## Docker

Build the API image:

```powershell
docker build -f deploy/Dockerfile.api -t humanproof-ai-api .
```

Run:

```powershell
docker run --rm -p 8765:8765 humanproof-ai-api
```

Compose:

```powershell
docker compose -f deploy/docker-compose.yml up --build
```

## Production Topology

Recommended services:

- API service behind a TLS load balancer
- asynchronous worker pool for extraction, OCR, AI calls, and report generation
- PostgreSQL for metadata and workflow state
- encrypted object storage for source files and reports
- Redis or managed queue for jobs and notifications
- vector database for semantic search and organization knowledge base
- SIEM/audit sink for append-only security events

## Environment Variables

Suggested production variables:

```text
HUMANPROOF_ENV=production
HUMANPROOF_DATABASE_URL=postgres://...
HUMANPROOF_OBJECT_STORAGE_URL=s3://...
HUMANPROOF_KMS_KEY_ID=...
HUMANPROOF_OIDC_ISSUER=...
HUMANPROOF_WEBHOOK_SIGNING_SECRET=...
HUMANPROOF_RETENTION_DAYS=365
```

## Release Gates

Before production release:

- unit tests pass
- integration tests pass
- accessibility smoke tests pass
- dependency and container scans pass
- secret scan passes
- database migrations are reviewed
- backup restore is tested
- incident rollback is documented
