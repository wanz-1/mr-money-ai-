# Mr Money AI

Mr Money AI is a cloud-deployable AI Document Intelligence Platform for professional writing review, transparent AI-writing analysis, citation checks, similarity review, fact-checking support, accessibility review, compliance triage, and publication readiness reporting.

**Live:** https://mr-money-ai.onrender.com

## Features

- **17 Specialized AI Agents** — Grammar, Readability, Structure, Similarity, Citation, Fact-Checking, AI Writing Analysis, Tone, Authorship Consistency, Accessibility, Compliance, Security, Argument Strength, Sentence Variety, Vocabulary Richness, Paragraph Balance, PII Detection
- **Explainable Scoring** — Every score includes AI-generated explanations, evidence, and confidence levels
- **SSE Streaming AI Chat** — Real-time token-by-token AI responses with document context
- **Image Generation** — `/imagine` or `/image` commands in the AI assistant
- **Document Templates** — 8 built-in templates (Research Paper, Thesis, Grant Proposal, Business Plan, etc.)
- **Document Comparison** — Side-by-side diff with similarity scoring
- **Auto-Formatting** — Automatic text cleanup and formatting
- **Text Humanization** — Rule-based writing improvements preserving meaning
- **13 Format Support** — TXT, MD, HTML, JSON, XML, CSV, LaTeX, RTF, DOCX, ODT, EPUB, XLSX, PPTX, PDF
- **Report Exports** — PDF, DOCX, HTML, Markdown
- **Auth & RBAC** — JWT authentication, 15 permissions, 5 roles
- **PWA** — Installable progressive web app with offline support
- **Dark Mode** — System preference detection + manual toggle

## Quick Start

```powershell
# Run tests
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1

# Start server
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1

# Open http://127.0.0.1:8765
```

## Deploy to Render (Free)

1. Push to GitHub
2. Go to https://dashboard.render.com/new
3. Connect repo, set build command: `pip install -r requirements.txt`
4. Set start command: `python -m backend.humanproof.server --host 0.0.0.0 --port $PORT`
5. Add env vars: `HP_AI_PROVIDER=custom`, `HP_CUSTOM_API_BASE=https://aimodelapi.onrender.com/v1`, `HP_CUSTOM_API_KEY=your-key`, `HP_CUSTOM_MODEL=dev-x`
6. Deploy

## Project Layout

```text
backend/humanproof/       Core analyzers, orchestration, API server, AI assistant, report exporters
frontend/                 Static Alpine.js SPA with PWA support
database/schema.sql       Enterprise PostgreSQL schema (17 tables, 14 indexes)
deploy/                   Docker and Compose deployment assets
scripts/                  Local helper scripts
tests/                    Test suite
android/                  Android TWA wrapper for Play Store
```

## Integrity Position

Mr Money AI does not claim to prove whether text was written by a human or by AI. Its AI-writing analysis is transparent and probabilistic, showing confidence estimates, evidence indicators, and limitations. Findings are decision support for responsible review, not misconduct determinations.

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
