# HumanProof AI

HumanProof AI is a local-first document intelligence platform for professional writing review, transparent AI-writing analysis, citation checks, similarity review, fact-checking support, accessibility review, compliance triage, and publication readiness reporting.

This repository contains a working foundation:

- Python standard-library backend and orchestration engine
- Specialized review agents for grammar, readability, structure, similarity, citation, fact-checking, tone, authorship consistency, accessibility, compliance, and security
- Best-effort extraction for TXT, Markdown, HTML, JSON, XML, CSV, RTF, DOCX, ODT, EPUB, XLSX, PPTX, and lightweight PDF text parsing
- Static responsive frontend for uploads, dashboards, findings, action plans, and report downloads
- Report exports for JSON, Markdown, HTML, DOCX, and PDF
- Database schema, API docs, deployment scripts, CI, and operational documentation

## Quick Start

Run the automated tests:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

Start the local web application:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1
```

Open:

```text
http://127.0.0.1:8765
```

Review a document from the CLI:

```powershell
uv run --no-project python -m backend.humanproof.cli path\to\document.md --format pdf
```

## Project Layout

```text
backend/humanproof/       Core analyzers, orchestration, API server, report exporters
frontend/                 Static browser application
database/schema.sql       Enterprise relational schema
deploy/                   Docker and Compose deployment assets
docs/                     User, admin, developer, API, security, and maintenance docs
scripts/                  Local helper scripts
tests/                    Standard-library test suite
```

## Integrity Position

HumanProof AI does not claim to prove whether text was written by a human or by AI. Its AI-writing analysis is transparent and probabilistic, showing confidence estimates, evidence indicators, and limitations. Findings are decision support for responsible review, not misconduct determinations.

## Documentation

- [System Architecture](docs/architecture.md)
- [API Documentation](docs/api.md)
- [Database Schema](docs/database-schema.md)
- [Security Implementation](docs/security.md)
- [Deployment Guide](docs/deployment.md)
- [User Manual](docs/user-manual.md)
- [Administrator Guide](docs/admin-guide.md)
- [Developer Documentation](docs/developer-guide.md)
- [Maintenance Guide](docs/maintenance-guide.md)
