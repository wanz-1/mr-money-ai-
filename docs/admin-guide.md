# Administrator Guide

## Tenant Setup

Production administrators should configure:

- organization profile
- domains and SSO
- MFA rules
- role templates
- workspace defaults
- retention policies
- style guides
- custom dictionaries
- approved source repositories
- webhook endpoints

## Roles

Recommended default roles:

- Owner: full organization administration
- Admin: user, workspace, policy, and integration management
- Editor: document upload, edit, review, and export
- Reviewer: comments, findings, approvals
- Viewer: read-only access
- Auditor: audit log and compliance report access

## Data Retention

Define retention per workspace:

- source file retention
- extracted text retention
- review report retention
- audit log retention
- deletion approval requirements

## Monitoring

Track:

- review latency
- extraction failures
- OCR queue depth
- AI provider errors
- report export failures
- authentication failures
- unusual export volume
- webhook delivery failures

## Incident Response

For suspected credential or sensitive-data exposure:

1. Disable affected API keys or user sessions.
2. Preserve audit logs.
3. Rotate exposed credentials.
4. Identify accessed documents and exports.
5. Notify compliance and legal stakeholders according to policy.
6. Document root cause and remediation.

