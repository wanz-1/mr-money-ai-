# System Architecture

HumanProof AI is organized as a modular document intelligence platform. The current implementation is local-first and dependency-light; enterprise capabilities are represented as explicit adapter boundaries so they can be replaced with managed services without changing the domain model.

## Runtime Layers

1. Frontend application
   - Static HTML, CSS, and JavaScript.
   - Handles upload, pasted text, dashboard rendering, finding filters, theme switching, and report downloads.
   - Calls the backend through JSON endpoints.

2. API service
   - `backend.humanproof.server` exposes health, capabilities, review creation, review retrieval, and report export endpoints.
   - The current storage layer is in-memory for local development.
   - Production deployments should replace this with the database schema in `database/schema.sql`.

3. Document extraction
   - `backend.humanproof.extractors` detects file types and extracts text.
   - Standard-library extraction supports text-like formats plus OpenXML/ODF/EPUB zip XML formats.
   - PDF extraction is lightweight and should be replaced by a PDF/OCR adapter for scanned or complex documents.

4. Master orchestration engine
   - `backend.humanproof.orchestrator` runs specialized agents and merges their findings.
   - It creates a single review report with metrics, findings, limitations, and an action plan.

5. Specialized agents
   - Grammar Agent
   - Writing Agent
   - Editing Agent
   - Similarity Agent
   - Citation Agent
   - Fact-Checking Agent
   - Transparent AI-Writing Analysis Agent
   - Tone Analysis Agent
   - Authorship Consistency Agent
   - Accessibility Agent
   - Compliance and Security Agent

6. Report generation
   - `backend.humanproof.reports` exports JSON, Markdown, HTML, DOCX, and PDF reports.
   - Reports include executive summary, metrics, detailed findings, action plan, limitations, and revision history.

## Enterprise Adapter Boundaries

The following capabilities are designed as adapters for production extension:

- OCR and high-fidelity PDF layout extraction
- Internet source matching and cross-language similarity search
- DOI, URL, Crossref, PubMed, Zotero, and Mendeley verification
- Fact-checking against approved source corpora
- Vector search and organization knowledge base
- SSO, SCIM, MFA, RBAC, and enterprise audit logging
- Real-time collaboration with operational transform or CRDT services
- Cloud storage integrations for Word, Google Docs, OneDrive, Drive, Dropbox, GitHub, and LibreOffice
- GPU-accelerated batch processing
- Long-term retention and legal hold policies

## Data Flow

1. User uploads or pastes a document.
2. Frontend sends text or base64 file content to `POST /api/reviews`.
3. Backend extracts text and captures metadata.
4. Orchestrator runs the agent pipeline.
5. Agent findings are normalized by severity, category, confidence, and recommendation.
6. Scores are aggregated into the document quality dashboard.
7. Report exporters generate downloadable review artifacts.

## AI Pipeline

The shipped pipeline is deterministic and local. It uses transparent heuristics for:

- grammar and style patterns
- readability and sentence rhythm
- internal similarity and repetition
- citation marker detection
- unsupported statistics and quotation triage
- AI-writing indicators such as vocabulary diversity, rhythm uniformity, repeated starts, and repetition
- accessibility markup checks
- privacy and credential leakage signals

Production AI adapters should follow the same contract:

- return evidence, not unexplained labels
- provide confidence estimates
- preserve citations and source context
- avoid fabricated claims
- expose limitations and model/version metadata
- keep human reviewers in control of publication decisions

## Scalability Model

Production scaling should split the API service from asynchronous workers:

- API: authentication, upload coordination, review retrieval, collaboration, webhooks
- Worker queue: extraction, OCR, similarity search, LLM calls, report generation
- Object storage: encrypted original files and generated reports
- Relational database: metadata, access control, findings, workflow state
- Vector database: semantic source matching and organization knowledge base
- Audit stream: append-only security and compliance events

