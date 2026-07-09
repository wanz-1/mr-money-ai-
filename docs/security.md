# Security Implementation

HumanProof AI is privacy-first and local-first by default. The current local server does not send document content to external services.

## Implemented Locally

- Local document processing without network calls
- Sensitive-data triage for email addresses, credential-like strings, and payment-card-like numbers
- CORS support for local frontend/API development
- Report limitations that prevent overclaiming AI-writing or fact-checking certainty
- Path traversal protection for static file serving

## Production Controls

Production deployments must implement the following controls before processing regulated or confidential documents:

- TLS 1.3 for external traffic
- service-to-service encryption
- end-to-end encryption option for highly sensitive workspaces
- MFA and SSO through OIDC/SAML
- role-based access control for organizations, workspaces, documents, reviews, exports, and admin actions
- least-privilege service accounts
- encrypted object storage with customer-managed key support
- encrypted database volumes and encrypted backups
- configurable retention and deletion workflows
- malware scanning on upload
- data-loss prevention rules for export and sharing
- audit logging for every sensitive action
- signed webhooks
- vulnerability scanning in CI
- secret scanning and rotation runbooks

## Compliance Alignment

The architecture supports GDPR, ISO 27001, and SOC 2 principles:

- GDPR: lawful basis tracking, retention controls, export/delete workflows, processor records
- ISO 27001: asset inventory, risk treatment, access control, incident handling, supplier controls
- SOC 2: security, availability, confidentiality, processing integrity, privacy controls

This repository is not itself a certification. Certification requires organizational policies, evidence collection, vendor reviews, monitoring, incident response, and third-party audit.

## AI Safety and Integrity

- AI-writing analysis is probabilistic and never definitive.
- Findings include confidence estimates and limitations.
- Human reviewers must make final academic, legal, compliance, and publishing decisions.
- The platform must not be marketed as bypassing AI detectors.
- Humanization features should improve clarity and preserve meaning, citations, and technical accuracy.

