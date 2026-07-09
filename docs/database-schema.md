# Database Schema

The production schema lives in `database/schema.sql`. It is designed around organizations, workspaces, documents, immutable versions, reviews, findings, collaboration, approval workflows, integrations, and audit logs.

## Core Tables

- `organizations`: tenant boundary, retention defaults, SSO configuration
- `users`: identity records linked to organizations
- `roles` and `role_assignments`: RBAC
- `workspaces`: team-level document containers
- `documents`: current document metadata
- `document_versions`: immutable uploaded or edited versions
- `reviews`: orchestration result per document version
- `findings`: normalized agent findings
- `metrics`: score values used by dashboards and reporting
- `citations`: extracted citation and source metadata
- `comments`: collaboration comments
- `approval_steps`: reviewer and publisher workflows
- `audit_logs`: append-only security and compliance events
- `api_keys`, `webhooks`, `integration_connections`: enterprise automation and integrations
- `knowledge_base_entries`: organization reference corpus
- `style_guide_terms`: terminology and style-guide enforcement

## Storage Principles

- Store original files in encrypted object storage, not directly in the relational database.
- Store cryptographic hashes for integrity checks.
- Store extracted text separately with strict access control and retention policies.
- Keep findings reproducible by storing agent name, version, evidence, confidence, and model metadata.
- Keep audit logs append-only.

