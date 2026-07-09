# Developer Documentation

## Code Map

- `backend/humanproof/models.py`: dataclasses used by the API, agents, and reports
- `backend/humanproof/extractors.py`: file detection and text extraction
- `backend/humanproof/analyzers.py`: specialized local review agents
- `backend/humanproof/orchestrator.py`: master review pipeline and score aggregation
- `backend/humanproof/reports.py`: JSON, Markdown, HTML, DOCX, and PDF exporters
- `backend/humanproof/server.py`: local HTTP API and static frontend server
- `backend/humanproof/cli.py`: command-line report generation
- `frontend/`: static application
- `tests/`: standard-library unit tests

## Add an Agent

1. Create a class with `name` and `analyze(self, document)`.
2. Return an `AgentResult`.
3. Include findings as `Finding` objects with severity, category, confidence, and recommendation.
4. Add the agent instance to `AGENTS` in `analyzers.py`.
5. Add tests for at least one positive and one no-finding path.

## Agent Contract

Agents must:

- preserve author intent
- avoid fabricated facts
- include confidence estimates
- expose limitations
- avoid definitive claims for probabilistic signals
- provide actionable recommendations

## API Development

The local server uses the Python standard library. Production teams can swap the API layer for FastAPI, Django, Flask, or another framework while preserving:

- `extract_document`
- `review_document`
- `ReviewReport.to_dict`
- `export_report`

## Testing

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

The tests avoid third-party dependencies so they can run in restricted environments.
