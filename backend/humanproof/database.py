"""PostgreSQL database connection and query layer for HumanProof AI."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Tuple

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
except ImportError:
    psycopg2 = None  # type: ignore[assignment]

from .models import utc_now


DATABASE_URL = os.environ.get("DATABASE_URL", "")
_pool: Optional[Any] = None


@dataclass
class DBConfig:
    dsn: str = ""
    min_connections: int = 2
    max_connections: int = 20
    connect_timeout: int = 10

    @classmethod
    def from_env(cls) -> DBConfig:
        return cls(dsn=DATABASE_URL or os.environ.get("PG_DSN", "postgresql://localhost:5432/humanproof"))


def init_pool(config: Optional[DBConfig] = None) -> None:
    global _pool
    if psycopg2 is None:
        return
    config = config or DBConfig.from_env()
    if not config.dsn:
        return
    _pool = psycopg2.pool.ThreadedConnectionPool(
        config.min_connections,
        config.max_connections,
        config.dsn,
        connect_timeout=config.connect_timeout,
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def get_connection() -> Generator[Any, None, None]:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    conn = _pool.getconn()
    try:
        conn.autocommit = False
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


@contextmanager
def get_cursor(conn: Any, name: Optional[str] = None) -> Generator[Any, None, None]:
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor if psycopg2 else None) if psycopg2 else None
    try:
        yield cursor
    finally:
        if cursor:
            cursor.close()


def is_available() -> bool:
    return psycopg2 is not None and _pool is not None


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return utc_now()


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=True, default=str)


# ---------------------------------------------------------------------------
# Organization queries
# ---------------------------------------------------------------------------

def create_organization(name: str, slug: str, retention_days: int = 365) -> Dict[str, Any]:
    org_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO organizations (id, name, slug, retention_days, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (org_id, name, slug, retention_days, now, now),
            )
    return {"id": org_id, "name": name, "slug": slug}


def get_organization(org_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM organizations WHERE id = %s", (org_id,))
            return dict(cur.fetchone()) if cur.fetchone() else None


# ---------------------------------------------------------------------------
# User queries
# ---------------------------------------------------------------------------

def create_user(
    org_id: str,
    email: str,
    display_name: str,
    password_hash: str,
    mfa_enabled: bool = False,
) -> Dict[str, Any]:
    user_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO users (id, organization_id, email, display_name, password_hash, mfa_enabled, status, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s) RETURNING id""",
                (user_id, org_id, email, display_name, password_hash, mfa_enabled, now, now),
            )
    return {"id": user_id, "organization_id": org_id, "email": email, "display_name": display_name}


def get_user_by_email(org_id: str, email: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id, organization_id, email, display_name, password_hash, mfa_enabled, status FROM users WHERE organization_id = %s AND email = %s",
                (org_id, email),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id, organization_id, email, display_name, mfa_enabled, status FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_user_mfa(user_id: str, mfa_enabled: bool) -> None:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute("UPDATE users SET mfa_enabled = %s, updated_at = %s WHERE id = %s", (mfa_enabled, _now(), user_id))


# ---------------------------------------------------------------------------
# Role queries
# ---------------------------------------------------------------------------

def create_role(org_id: str, name: str, permissions: List[str]) -> Dict[str, Any]:
    role_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO roles (id, organization_id, name, permissions, created_at)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (role_id, org_id, name, _json(permissions), now),
            )
    return {"id": role_id, "name": name, "permissions": permissions}


def assign_role(user_id: str, role_id: str, scope_type: str = "organization", scope_id: Optional[str] = None) -> None:
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO role_assignments (user_id, role_id, scope_type, scope_id, created_at)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (user_id, role_id, scope_type, scope_id, now),
            )


def get_user_roles(user_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT r.name, r.permissions, ra.scope_type, ra.scope_id
                   FROM role_assignments ra JOIN roles r ON ra.role_id = r.id
                   WHERE ra.user_id = %s""",
                (user_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def get_user_permissions(user_id: str) -> List[str]:
    roles = get_user_roles(user_id)
    permissions: set = set()
    for role in roles:
        perms = role.get("permissions", [])
        if isinstance(perms, str):
            perms = json.loads(perms)
        permissions.update(perms)
    return sorted(permissions)


# ---------------------------------------------------------------------------
# Workspace queries
# ---------------------------------------------------------------------------

def create_workspace(org_id: str, name: str, created_by: Optional[str] = None, retention_days: Optional[int] = None) -> Dict[str, Any]:
    ws_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO workspaces (id, organization_id, name, retention_days, created_by, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (ws_id, org_id, name, retention_days, created_by, now),
            )
    return {"id": ws_id, "name": name}


def list_workspaces(org_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute("SELECT id, name, created_at FROM workspaces WHERE organization_id = %s ORDER BY created_at DESC", (org_id,))
            return [dict(row) for row in cur.fetchall()]


def get_workspace(ws_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM workspaces WHERE id = %s", (ws_id,))
            row = cur.fetchone()
            return dict(row) if row else None


# ---------------------------------------------------------------------------
# Document queries
# ---------------------------------------------------------------------------

def create_document(
    org_id: str,
    ws_id: str,
    title: str,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    doc_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO documents (id, organization_id, workspace_id, title, status, created_by, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s) RETURNING id""",
                (doc_id, org_id, ws_id, title, created_by, now, now),
            )
    return {"id": doc_id, "title": title, "status": "draft"}


def create_document_version(
    doc_id: str,
    version_number: int,
    file_format: str,
    content_type: str,
    object_uri: str,
    sha256: str,
    size_bytes: int,
    created_by: Optional[str] = None,
    extracted_text_uri: Optional[str] = None,
) -> Dict[str, Any]:
    ver_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO document_versions
                   (id, document_id, version_number, file_format, content_type, object_uri,
                    extracted_text_uri, sha256, size_bytes, created_by, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (ver_id, doc_id, version_number, file_format, content_type, object_uri,
                 extracted_text_uri, sha256, size_bytes, created_by, now),
            )
            cur.execute("UPDATE documents SET current_version_id = %s, updated_at = %s WHERE id = %s", (ver_id, now, doc_id))
    return {"id": ver_id, "version_number": version_number}


def list_documents(org_id: str, ws_id: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            if ws_id:
                cur.execute(
                    "SELECT id, title, status, created_at, updated_at FROM documents WHERE organization_id = %s AND workspace_id = %s ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                    (org_id, ws_id, limit, offset),
                )
            else:
                cur.execute(
                    "SELECT id, title, status, created_at, updated_at FROM documents WHERE organization_id = %s ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                    (org_id, limit, offset),
                )
            return [dict(row) for row in cur.fetchall()]


def get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM documents WHERE id = %s", (doc_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_document_versions(doc_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id, version_number, file_format, size_bytes, created_by, created_at FROM document_versions WHERE document_id = %s ORDER BY version_number DESC",
                (doc_id,),
            )
            return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Review queries
# ---------------------------------------------------------------------------

def create_review(
    doc_id: str,
    version_id: str,
    summary: str,
    publication_readiness: float,
    analysis_mode: str,
    created_by: Optional[str] = None,
    agent_versions: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    review_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO reviews
                   (id, document_id, document_version_id, status, summary, publication_readiness,
                    analysis_mode, agent_versions, created_by, created_at)
                   VALUES (%s, %s, %s, 'completed', %s, %s, %s, %s, %s, %s) RETURNING id""",
                (review_id, doc_id, version_id, summary, publication_readiness, analysis_mode,
                 _json(agent_versions or {}), created_by, now),
            )
    return {"id": review_id}


def create_finding(
    review_id: str,
    agent: str,
    category: str,
    severity: str,
    title: str,
    message: str,
    recommendation: str,
    confidence: float,
    span_start: Optional[int] = None,
    span_end: Optional[int] = None,
    excerpt: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> str:
    finding_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO findings
                   (id, review_id, agent, category, severity, title, message, recommendation,
                    confidence, span_start, span_end, excerpt, evidence, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (finding_id, review_id, agent, category, severity, title, message, recommendation,
                 confidence, span_start, span_end, excerpt, _json(evidence or {}), now),
            )
    return finding_id


def create_metric(review_id: str, name: str, value: float, details: Optional[Dict[str, Any]] = None) -> None:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO metrics (review_id, name, value, details) VALUES (%s, %s, %s, %s)",
                (review_id, name, value, _json(details or {})),
            )


def get_review(review_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM reviews WHERE id = %s", (review_id,))
            row = cur.fetchone()
            if not row:
                return None
            review = dict(row)
            cur.execute("SELECT * FROM findings WHERE review_id = %s ORDER BY severity DESC", (review_id,))
            review["findings"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT name, value, details FROM metrics WHERE review_id = %s", (review_id,))
            review["metrics"] = {row["name"]: row["value"] for row in cur.fetchall()}
            return review


# ---------------------------------------------------------------------------
# Comment queries
# ---------------------------------------------------------------------------

def create_comment(
    doc_id: str,
    author_id: str,
    body: str,
    document_version_id: Optional[str] = None,
    span_start: Optional[int] = None,
    span_end: Optional[int] = None,
) -> Dict[str, Any]:
    comment_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO comments (id, document_id, document_version_id, author_id, body, span_start, span_end, status, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s) RETURNING id""",
                (comment_id, doc_id, document_version_id, author_id, body, span_start, span_end, now),
            )
    return {"id": comment_id}


def list_comments(doc_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT c.*, u.display_name as author_name
                   FROM comments c LEFT JOIN users u ON c.author_id = u.id
                   WHERE c.document_id = %s ORDER BY c.created_at""",
                (doc_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def resolve_comment(comment_id: str) -> None:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute("UPDATE comments SET status = 'resolved', resolved_at = %s WHERE id = %s", (_now(), comment_id))


# ---------------------------------------------------------------------------
# Approval workflow queries
# ---------------------------------------------------------------------------

def create_approval_step(
    doc_id: str,
    reviewer_id: str,
    step_order: int,
) -> Dict[str, Any]:
    step_id = _new_id()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO approval_steps (id, document_id, reviewer_id, step_order, status)
                   VALUES (%s, %s, %s, %s, 'pending') RETURNING id""",
                (step_id, doc_id, reviewer_id, step_order),
            )
    return {"id": step_id}


def decide_approval_step(step_id: str, decision: str, note: Optional[str] = None) -> None:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "UPDATE approval_steps SET status = %s, decision_note = %s, decided_at = %s WHERE id = %s",
                (decision, note, _now(), step_id),
            )


def list_approval_steps(doc_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """SELECT a.*, u.display_name as reviewer_name
                   FROM approval_steps a LEFT JOIN users u ON a.reviewer_id = u.id
                   WHERE a.document_id = %s ORDER BY a.step_order""",
                (doc_id,),
            )
            return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Audit log queries
# ---------------------------------------------------------------------------

def write_audit_log(
    org_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    log_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO audit_logs (id, organization_id, actor_id, action, resource_type, resource_id, ip_address, user_agent, metadata, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (log_id, org_id, actor_id, action, resource_type, resource_id, ip_address, user_agent, _json(metadata or {}), now),
            )


def list_audit_logs(org_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT * FROM audit_logs WHERE organization_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (org_id, limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Knowledge base queries
# ---------------------------------------------------------------------------

def create_knowledge_entry(
    org_id: str,
    title: str,
    content_hash: str,
    source_uri: Optional[str] = None,
    embedding_ref: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO knowledge_base_entries (id, organization_id, title, source_uri, content_hash, embedding_ref, metadata, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (entry_id, org_id, title, source_uri, content_hash, embedding_ref, _json(metadata or {}), now),
            )
    return {"id": entry_id, "title": title}


# ---------------------------------------------------------------------------
# Style guide queries
# ---------------------------------------------------------------------------

def create_style_term(
    org_id: str,
    term: str,
    preferred_term: Optional[str],
    rule: str,
    severity: str = "low",
) -> Dict[str, Any]:
    term_id = _new_id()
    now = _now()
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                """INSERT INTO style_guide_terms (id, organization_id, term, preferred_term, rule, severity, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (term_id, org_id, term, preferred_term, rule, severity, now),
            )
    return {"id": term_id, "term": term, "preferred_term": preferred_term}


def list_style_terms(org_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id, term, preferred_term, rule, severity FROM style_guide_terms WHERE organization_id = %s",
                (org_id,),
            )
            return [dict(row) for row in cur.fetchall()]
