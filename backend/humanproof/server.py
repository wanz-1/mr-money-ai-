"""Local HTTP API and static frontend server for Mr Money AI."""

from __future__ import annotations

from .config import load_env
load_env()

import argparse
import base64
import json
import logging
import mimetypes
import os
import time
from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger("humanproof.server")


class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._max = max_requests
        self._window = window_seconds

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        self._requests[key] = [t for t in self._requests[key] if now - t < self._window]
        if len(self._requests[key]) >= self._max:
            return False
        self._requests[key].append(now)
        return True


_auth_limiter = RateLimiter(max_requests=10, window_seconds=60)

from .ai_assistant import (
    chat as ai_chat,
    chat_stream as ai_chat_stream,
    create_session as ai_create_session,
    generate_image as ai_generate_image,
    get_provider_info,
    get_session as ai_get_session,
)
from .audit import audit, init_audit_logger, shutdown_audit_logger
from .auth import create_access_token, create_refresh_token, decode_token, hash_password, refresh_access_token, verify_password
from .extractors import SUPPORTED_FORMATS, extract_document
from .middleware import (
    AuthContext,
    MiddlewareResult,
    apply_cors_headers,
    apply_security_headers,
    authenticate_request,
    get_client_ip,
    run_middleware,
    sanitize_filename,
    validate_json_body,
)
from .models import Document, DocumentMetadata, ReviewReport
from .orchestrator import review_document, review_text
from .rbac import Permission, has_permission
from .reports import export_report


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "frontend"
REVIEWS: Dict[str, ReviewReport] = {}


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------

class HumanProofHandler(BaseHTTPRequestHandler):
    server_version = "MrMoneyAI/0.2"

    def do_OPTIONS(self) -> None:
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parsed.query

        if path == "/health":
            self._send_json({"status": "ok", "service": "humanproof-ai", "version": "0.2.0"})
            return

        if path == "/api/capabilities":
            self._send_json(self._capabilities())
            return

        if path == "/api/auth/me":
            self._handle_auth_me()
            return

        if path == "/api/documents":
            self._handle_list_documents(query)
            return

        if path.startswith("/api/documents/") and path.endswith("/versions"):
            self._handle_document_versions(path)
            return

        if path.startswith("/api/documents/") and "/comments" in path:
            self._handle_list_comments(path)
            return

        if path.startswith("/api/documents/") and "/approval" in path:
            self._handle_list_approval(path)
            return

        if path.startswith("/api/workspaces"):
            self._handle_list_workspaces()
            return

        if path == "/api/templates":
            self._handle_list_templates()
            return

        if path.startswith("/api/reviews/"):
            self._handle_review_get(path)
            return

        if path.startswith("/api/audit-logs"):
            self._handle_audit_logs(query)
            return

        if path == "/api/ai/providers":
            self._handle_ai_providers()
            return

        if path.startswith("/api/ai/sessions/"):
            self._handle_ai_session_get(path)
            return

        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/auth/register":
            self._handle_register()
            return

        if path == "/api/auth/login":
            self._handle_login()
            return

        if path == "/api/auth/refresh":
            self._handle_refresh()
            return

        if path == "/api/reviews":
            self._handle_review_post()
            return

        if path == "/api/documents":
            self._handle_create_document()
            return

        if path.startswith("/api/documents/") and path.endswith("/reviews"):
            self._handle_document_review(path)
            return

        if path.startswith("/api/documents/") and "/comments" in path:
            self._handle_add_comment(path)
            return

        if path.startswith("/api/documents/") and path.endswith("/approve"):
            self._handle_approval_decision(path)
            return

        if path == "/api/workspaces":
            self._handle_create_workspace()
            return

        if path == "/api/compare":
            self._handle_document_compare()
            return

        if path.startswith("/api/documents/") and path.endswith("/format"):
            self._handle_format_document(path)
            return

        if path.startswith("/api/documents/") and path.endswith("/humanize"):
            self._handle_humanize(path)
            return

        if path.startswith("/api/research/"):
            self._handle_research(path)
            return

        if path == "/api/ai/sessions":
            self._handle_ai_session_create()
            return

        if path == "/api/ai/chat":
            self._handle_ai_chat()
            return

        if path == "/api/ai/chat/stream":
            self._handle_ai_chat_stream()
            return

        if path == "/api/ai/image":
            self._handle_ai_image()
            return

        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    # -----------------------------------------------------------------------
    # Auth endpoints
    # -----------------------------------------------------------------------

    def _handle_register(self) -> None:
        mw = run_middleware(self)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        client_ip = get_client_ip(self)
        if not _auth_limiter.is_allowed(client_ip):
            self._send_json({"error": "Too many attempts. Try again later."}, HTTPStatus.TOO_MANY_REQUESTS)
            return

        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        display_name = (data.get("displayName") or "").strip()
        org_name = (data.get("organizationName") or "").strip()

        if not email or "@" not in email:
            self._send_json({"error": "Valid email required."}, HTTPStatus.BAD_REQUEST)
            return
        if len(password) < 8:
            self._send_json({"error": "Password must be at least 8 characters."}, HTTPStatus.BAD_REQUEST)
            return
        if not display_name:
            self._send_json({"error": "Display name required."}, HTTPStatus.BAD_REQUEST)
            return

        try:
            from . import database
            if database.is_available():
                slug = email.split("@")[0].replace(".", "-")
                org = database.create_organization(org_name or f"{display_name}'s Organization", slug)
                password_hash = hash_password(password)
                user = database.create_user(org["id"], email, display_name, password_hash)
                from .rbac import DEFAULT_ROLES_SETUP, Role
                for role, perms in DEFAULT_ROLES_SETUP:
                    existing = database.get_user_roles(user["id"])
                    if not any(r["name"] == role.value for r in existing):
                        database.create_role(org["id"], role.value, perms)
                        role_rows = [r for r in database.get_user_roles(user["id"]) if r["name"] == role.value]
                        if role_rows:
                            database.assign_role(user["id"], role_rows[0].get("id", "") if isinstance(role_rows[0], dict) else "")
                permissions = database.get_user_permissions(user["id"])
                access = create_access_token(user["id"], org["id"], permissions)
                refresh = create_refresh_token(user["id"], org["id"])
                audit(org["id"], "user.register", "user", user["id"], user["id"], get_client_ip(self))
                self._send_json({
                    "userId": user["id"],
                    "orgId": org["id"],
                    "email": email,
                    "displayName": display_name,
                    "accessToken": access,
                    "refreshToken": refresh,
                }, HTTPStatus.CREATED)
                return
        except Exception as exc:
            logger.exception("Registration failed")
            self._send_json({"error": "Registration failed. Please try again."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"error": "Database not configured. Set DATABASE_URL."}, HTTPStatus.SERVICE_UNAVAILABLE)

    def _handle_login(self) -> None:
        mw = run_middleware(self)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        client_ip = get_client_ip(self)
        if not _auth_limiter.is_allowed(client_ip):
            self._send_json({"error": "Too many attempts. Try again later."}, HTTPStatus.TOO_MANY_REQUESTS)
            return

        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        org_id = data.get("orgId") or ""

        if not email or not password:
            self._send_json({"error": "Email and password required."}, HTTPStatus.BAD_REQUEST)
            return

        try:
            from . import database
            if database.is_available():
                if org_id:
                    user = database.get_user_by_email(org_id, email)
                else:
                    user = None
                if not user:
                    self._send_json({"error": "Invalid credentials."}, HTTPStatus.UNAUTHORIZED)
                    return
                if not verify_password(password, user["password_hash"]):
                    self._send_json({"error": "Invalid credentials."}, HTTPStatus.UNAUTHORIZED)
                    return
                permissions = database.get_user_permissions(user["id"])
                access = create_access_token(user["id"], user["organization_id"], permissions)
                refresh = create_refresh_token(user["id"], user["organization_id"])
                audit(user["organization_id"], "user.login", "user", user["id"], user["id"], get_client_ip(self))
                self._send_json({
                    "userId": user["id"],
                    "orgId": user["organization_id"],
                    "email": user["email"],
                    "displayName": user["display_name"],
                    "accessToken": access,
                    "refreshToken": refresh,
                })
                return
        except Exception as exc:
            logger.exception("Login failed")

        self._send_json({"error": "Database not configured."}, HTTPStatus.SERVICE_UNAVAILABLE)

    def _handle_refresh(self) -> None:
        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        refresh_token = data.get("refreshToken") or ""
        if not refresh_token:
            self._send_json({"error": "Refresh token required."}, HTTPStatus.BAD_REQUEST)
            return

        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            self._send_json({"error": "Invalid refresh token."}, HTTPStatus.UNAUTHORIZED)
            return

        try:
            from . import database
            if database.is_available():
                permissions = database.get_user_permissions(payload["sub"])
                new_access = refresh_access_token(refresh_token, permissions)
                if new_access:
                    self._send_json({"accessToken": new_access})
                    return
        except Exception as exc:
            logger.exception("Token refresh failed")

        self._send_json({"error": "Token refresh failed."}, HTTPStatus.UNAUTHORIZED)

    def _handle_auth_me(self) -> None:
        mw = run_middleware(self, require_auth=True)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        auth = mw.auth_context
        try:
            from . import database
            if database.is_available() and auth.user_id:
                user = database.get_user_by_id(auth.user_id)
                if user:
                    self._send_json({
                        "userId": user["id"],
                        "orgId": user["organization_id"],
                        "email": user["email"],
                        "displayName": user["display_name"],
                        "permissions": auth.permissions,
                    })
                    return
        except Exception as exc:
            logger.exception("Failed to fetch user profile")

        self._send_json({"userId": auth.user_id, "orgId": auth.org_id, "permissions": auth.permissions})

    # -----------------------------------------------------------------------
    # Document endpoints
    # -----------------------------------------------------------------------

    def _handle_create_document(self) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.WRITE)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        title = (data.get("title") or "").strip()
        ws_id = data.get("workspaceId")

        if not title:
            self._send_json({"error": "Title required."}, HTTPStatus.BAD_REQUEST)
            return

        try:
            from . import database
            if database.is_available() and mw.auth_context.org_id:
                if not ws_id:
                    workspaces = database.list_workspaces(mw.auth_context.org_id)
                    if workspaces:
                        ws_id = workspaces[0]["id"]
                    else:
                        ws = database.create_workspace(mw.auth_context.org_id, "Default", mw.auth_context.user_id)
                        ws_id = ws["id"]
                doc = database.create_document(mw.auth_context.org_id, ws_id, title, mw.auth_context.user_id)
                audit(mw.auth_context.org_id, "document.create", "document", doc["id"], mw.auth_context.user_id, get_client_ip(self))
                self._send_json(doc, HTTPStatus.CREATED)
                return
        except Exception as exc:
            logger.exception("Failed to create document")
            self._send_json({"error": "Failed to create document."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json({"error": "Database not configured."}, HTTPStatus.SERVICE_UNAVAILABLE)

    def _handle_list_documents(self, query: str) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.READ)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        try:
            from . import database
            if database.is_available() and mw.auth_context.org_id:
                params = dict(p.split("=") for p in query.split("&") if "=" in p) if query else {}
                limit = int(params.get("limit", "50"))
                offset = int(params.get("offset", "0"))
                ws_id = params.get("workspaceId")
                docs = database.list_documents(mw.auth_context.org_id, ws_id, limit, offset)
                self._send_json({"documents": docs})
                return
        except Exception as exc:
            logger.exception("Failed to list documents")

        self._send_json({"documents": []})

    def _handle_document_versions(self, path: str) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.READ)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        parts = [unquote(p) for p in path.split("/") if p]
        if len(parts) < 4:
            self._send_json({"error": "Document ID required."}, HTTPStatus.BAD_REQUEST)
            return

        doc_id = parts[2]
        try:
            from . import database
            if database.is_available():
                versions = database.get_document_versions(doc_id)
                self._send_json({"versions": versions})
                return
        except Exception as exc:
            logger.exception("Failed to fetch document versions")

        self._send_json({"versions": []})

    def _handle_document_review(self, path: str) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.REVIEW)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        parts = [unquote(p) for p in path.split("/") if p]
        doc_id = parts[2] if len(parts) >= 3 else None
        if not doc_id:
            self._send_json({"error": "Document ID required."}, HTTPStatus.BAD_REQUEST)
            return

        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        filename = data.get("filename") or "upload.txt"
        content_type = data.get("contentType") or ""

        try:
            if "contentBase64" in data:
                file_data = base64.b64decode(data["contentBase64"])
                document = extract_document(file_data, filename, content_type)
            else:
                text = str(data.get("content", ""))
                metadata = DocumentMetadata(
                    filename=filename,
                    file_format=filename.rsplit(".", 1)[-1] if "." in filename else "txt",
                    content_type="text/plain",
                    size_bytes=len(text.encode("utf-8")),
                )
                document = Document(text=text, metadata=metadata)

            report = review_document(document)
            REVIEWS[report.review_id] = report

            try:
                from . import database
                if database.is_available() and mw.auth_context.org_id:
                    database.create_review(
                        doc_id=doc_id,
                        version_id="",
                        summary=report.summary,
                        publication_readiness=report.scores.get("publication_readiness", 0),
                        analysis_mode="local-first",
                        created_by=mw.auth_context.user_id,
                    )
                    for finding in report.findings:
                        database.create_finding(
                            review_id=report.review_id,
                            agent=finding.agent,
                            category=finding.category,
                            severity=finding.severity,
                            title=finding.title,
                            message=finding.message,
                            recommendation=finding.recommendation,
                            confidence=finding.confidence,
                            span_start=finding.span.start if finding.span else None,
                            span_end=finding.span.end if finding.span else None,
                            excerpt=finding.span.excerpt if finding.span else None,
                            evidence=finding.evidence,
                        )
                    for name, value in report.scores.items():
                        database.create_metric(report.review_id, name, value)
            except Exception as exc:
                logger.exception("Failed to persist review to database")

            audit(mw.auth_context.org_id, "review.create", "review", report.review_id, mw.auth_context.user_id, get_client_ip(self))
            self._send_json(report.to_dict(), HTTPStatus.CREATED)
        except Exception as exc:
            logger.exception("Document review failed")
            self._send_json({"error": "Review failed. Please try again."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    # -----------------------------------------------------------------------
    # Workspace endpoints
    # -----------------------------------------------------------------------

    def _handle_create_workspace(self) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.MANAGE_WORKSPACE)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        name = (data.get("name") or "").strip()
        if not name:
            self._send_json({"error": "Name required."}, HTTPStatus.BAD_REQUEST)
            return

        try:
            from . import database
            if database.is_available() and mw.auth_context.org_id:
                ws = database.create_workspace(mw.auth_context.org_id, name, mw.auth_context.user_id)
                self._send_json(ws, HTTPStatus.CREATED)
                return
        except Exception as exc:
            logger.exception("Failed to create workspace")

        self._send_json({"error": "Database not configured."}, HTTPStatus.SERVICE_UNAVAILABLE)

    def _handle_list_workspaces(self) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.READ)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        try:
            from . import database
            if database.is_available() and mw.auth_context.org_id:
                workspaces = database.list_workspaces(mw.auth_context.org_id)
                self._send_json({"workspaces": workspaces})
                return
        except Exception as exc:
            logger.exception("Failed to list workspaces")

        self._send_json({"workspaces": []})

    # -----------------------------------------------------------------------
    # Comment endpoints
    # -----------------------------------------------------------------------

    def _handle_add_comment(self, path: str) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.WRITE)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        parts = [unquote(p) for p in path.split("/") if p]
        doc_id = parts[2] if len(parts) >= 3 else None
        if not doc_id:
            self._send_json({"error": "Document ID required."}, HTTPStatus.BAD_REQUEST)
            return

        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        body = (data.get("body") or "").strip()
        if not body:
            self._send_json({"error": "Comment body required."}, HTTPStatus.BAD_REQUEST)
            return

        try:
            from . import database
            if database.is_available():
                comment = database.create_comment(
                    doc_id, mw.auth_context.user_id, body,
                    data.get("documentVersionId"),
                    data.get("spanStart"),
                    data.get("spanEnd"),
                )
                self._send_json(comment, HTTPStatus.CREATED)
                return
        except Exception as exc:
            logger.exception("Failed to add comment")

        self._send_json({"error": "Database not configured."}, HTTPStatus.SERVICE_UNAVAILABLE)

    def _handle_list_comments(self, path: str) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.READ)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        parts = [unquote(p) for p in path.split("/") if p]
        doc_id = parts[2] if len(parts) >= 3 else None
        if not doc_id:
            self._send_json({"error": "Document ID required."}, HTTPStatus.BAD_REQUEST)
            return

        try:
            from . import database
            if database.is_available():
                comments = database.list_comments(doc_id)
                self._send_json({"comments": comments})
                return
        except Exception as exc:
            logger.exception("Failed to list comments")

        self._send_json({"comments": []})

    # -----------------------------------------------------------------------
    # Approval workflow endpoints
    # -----------------------------------------------------------------------

    def _handle_list_approval(self, path: str) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.READ)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        parts = [unquote(p) for p in path.split("/") if p]
        doc_id = parts[2] if len(parts) >= 3 else None

        try:
            from . import database
            if database.is_available() and doc_id:
                steps = database.list_approval_steps(doc_id)
                self._send_json({"steps": steps})
                return
        except Exception as exc:
            logger.exception("Failed to list approval steps")

        self._send_json({"steps": []})

    def _handle_approval_decision(self, path: str) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.REVIEW)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        step_id = data.get("stepId")
        decision = data.get("decision")
        note = data.get("note")

        if not step_id or decision not in ("approved", "rejected", "changes_requested"):
            self._send_json({"error": "stepId and valid decision required."}, HTTPStatus.BAD_REQUEST)
            return

        try:
            from . import database
            if database.is_available():
                database.decide_approval_step(step_id, decision, note)
                self._send_json({"status": decision})
                return
        except Exception as exc:
            logger.exception("Failed to process approval decision")

        self._send_json({"error": "Database not configured."}, HTTPStatus.SERVICE_UNAVAILABLE)

    # -----------------------------------------------------------------------
    # Feature stubs (to be fully implemented in later phases)
    # -----------------------------------------------------------------------

    def _handle_document_compare(self) -> None:
        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return
        old_text = (data.get("original") or data.get("oldText") or "").strip()
        new_text = (data.get("modified") or data.get("newText") or "").strip()
        if not old_text and not new_text:
            self._send_json({"error": "Provide 'original' and 'modified' text to compare."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            from .comparison import compare_documents
            result = compare_documents(old_text, new_text)
            self._send_json(result.to_dict())
        except Exception as exc:
            logger.exception("Document comparison failed")
            self._send_json({"error": "Comparison failed."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_format_document(self, path: str) -> None:
        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return
        text = (data.get("text") or data.get("content") or "").strip()
        if not text:
            self._send_json({"error": "Provide 'text' to format."}, HTTPStatus.BAD_REQUEST)
            return
        formatted = _auto_format(text)
        self._send_json({"formatted": formatted, "original_length": len(text), "formatted_length": len(formatted)})

    def _handle_humanize(self, path: str) -> None:
        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return
        text = (data.get("text") or data.get("content") or "").strip()
        mode = data.get("mode", "professional")
        if not text:
            self._send_json({"error": "Provide 'text' to humanize."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = _humanize_text(text, mode)
            self._send_json(result)
        except Exception as exc:
            logger.exception("Humanization failed")
            self._send_json({"error": "Humanization failed."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_research(self, path: str) -> None:
        self._send_json({"error": "Research intelligence requires the research module (Phase 5)."}, HTTPStatus.NOT_IMPLEMENTED)

    def _handle_list_templates(self) -> None:
        try:
            from .templates import list_templates
            templates = list_templates()
            self._send_json({"templates": templates, "count": len(templates)})
        except Exception as exc:
            logger.exception("Failed to list templates")
            self._send_json({"error": "Failed to load templates."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    # -----------------------------------------------------------------------
    # Audit log endpoint
    # -----------------------------------------------------------------------

    def _handle_audit_logs(self, query: str) -> None:
        mw = run_middleware(self, require_auth=True, required_permission=Permission.VIEW_AUDIT_LOGS)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        try:
            from . import database
            if database.is_available() and mw.auth_context.org_id:
                params = dict(p.split("=") for p in query.split("&") if "=" in p) if query else {}
                limit = int(params.get("limit", "100"))
                logs = database.list_audit_logs(mw.auth_context.org_id, limit)
                self._send_json({"logs": logs})
                return
        except Exception as exc:
            logger.exception("Failed to fetch audit logs")

        self._send_json({"logs": []})

    # -----------------------------------------------------------------------
    # AI Assistant endpoints
    # -----------------------------------------------------------------------

    def _handle_ai_providers(self) -> None:
        self._send_json(get_provider_info())

    def _handle_ai_session_create(self) -> None:
        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        session = ai_create_session(
            document_text=data.get("documentText"),
            document_name=data.get("documentName"),
            review_data=data.get("reviewData"),
        )
        self._send_json(session.to_dict(), HTTPStatus.CREATED)

    def _handle_ai_session_get(self, path: str) -> None:
        parts = [unquote(p) for p in path.split("/") if p]
        if len(parts) < 4:
            self._send_json({"error": "Session ID required."}, HTTPStatus.BAD_REQUEST)
            return
        session_id = parts[3]
        session = ai_get_session(session_id)
        if not session:
            self._send_json({"error": "Session not found."}, HTTPStatus.NOT_FOUND)
            return
        self._send_json(session.to_dict())

    def _handle_ai_chat(self) -> None:
        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        session_id = data.get("sessionId", "")
        message = (data.get("message") or "").strip()

        if not message:
            self._send_json({"error": "Message required."}, HTTPStatus.BAD_REQUEST)
            return

        if not session_id:
            session = ai_create_session(
                document_text=data.get("documentText"),
                document_name=data.get("documentName"),
                review_data=data.get("reviewData"),
            )
            session_id = session.session_id

        result = ai_chat(session_id, message)
        if "error" in result:
            self._send_json(result, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result)

    def _handle_ai_chat_stream(self) -> None:
        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        session_id = data.get("sessionId", "")
        message = (data.get("message") or "").strip()

        if not message:
            self._send_json({"error": "Message required."}, HTTPStatus.BAD_REQUEST)
            return

        if not session_id:
            session = ai_create_session(
                document_text=data.get("documentText"),
                document_name=data.get("documentName"),
                review_data=data.get("reviewData"),
            )
            session_id = session.session_id

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        apply_cors_headers(self)
        self.end_headers()

        try:
            for event in ai_chat_stream(session_id, message):
                self.wfile.write(event.encode("utf-8"))
                self.wfile.flush()
        except Exception as exc:
            logger.exception("AI chat stream interrupted")

    def _handle_ai_image(self) -> None:
        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            self._send_json({"error": "Prompt required."}, HTTPStatus.BAD_REQUEST)
            return

        size = data.get("size", "1024x1024")
        n = int(data.get("n", 1))

        result = ai_generate_image(prompt, size, n)
        if "error" in result:
            self._send_json(result, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result)

    # -----------------------------------------------------------------------
    # Original review endpoints (backward compatible)
    # -----------------------------------------------------------------------

    def _handle_review_post(self) -> None:
        mw = run_middleware(self)
        if not mw.ok:
            self._send_json({"error": mw.error}, mw.status)
            return

        data, err = validate_json_body(self._read_raw_body())
        if err:
            self._send_json({"error": err}, HTTPStatus.BAD_REQUEST)
            return

        filename = sanitize_filename(data.get("filename") or "upload.txt")
        content_type = data.get("contentType") or ""

        try:
            if "contentBase64" in data:
                file_data = base64.b64decode(data["contentBase64"])
                document = extract_document(file_data, filename, content_type)
            else:
                text = str(data.get("content", ""))
                metadata = DocumentMetadata(
                    filename=filename,
                    file_format=filename.rsplit(".", 1)[-1] if "." in filename else "txt",
                    content_type="text/plain",
                    size_bytes=len(text.encode("utf-8")),
                )
                document = Document(text=text, metadata=metadata)

            report = review_document(document)
            REVIEWS[report.review_id] = report
            self._send_json(report.to_dict(), HTTPStatus.CREATED)
        except Exception as exc:
            logger.exception("Review failed")
            self._send_json({"error": "Review failed. Please try again."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_review_get(self, path: str) -> None:
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) < 3:
            self._send_json({"error": "Review ID required."}, HTTPStatus.BAD_REQUEST)
            return
        review_id = parts[2]
        report = REVIEWS.get(review_id)
        if not report:
            self._send_json({"error": "Review not found."}, HTTPStatus.NOT_FOUND)
            return
        if len(parts) == 3:
            self._send_json(report.to_dict())
            return
        if len(parts) == 5 and parts[3] == "reports":
            try:
                body, content_type, extension = export_report(report, parts[4])
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self.send_response(HTTPStatus.OK)
            self._headers(content_type)
            safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in report.document.filename.rsplit(".", 1)[0])
            self.send_header("Content-Disposition", f'attachment; filename="{safe_name}-humanproof-report.{extension}"')
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    # -----------------------------------------------------------------------
    # Capabilities
    # -----------------------------------------------------------------------

    def _capabilities(self) -> dict:
        return {
            "formats": SUPPORTED_FORMATS,
            "reportFormats": ["json", "md", "html", "docx", "pdf"],
            "agents": [
                "Grammar Agent",
                "Writing Agent",
                "Editing Agent",
                "Similarity Agent",
                "Citation Agent",
                "Fact-Checking Agent",
                "Transparent AI-Writing Analysis Agent",
                "Tone Analysis Agent",
                "Authorship Consistency Agent",
                "Accessibility Agent",
                "Compliance and Security Agent",
            ],
            "features": [
                "authentication",
                "rbac",
                "audit_logging",
                "document_management",
                "workspace_management",
                "comments",
                "approval_workflows",
                "ai_assistant",
            ],
            "analysisMode": "local-first transparent decision support",
        }

    # -----------------------------------------------------------------------
    # Static file serving
    # -----------------------------------------------------------------------

    def _serve_static(self, request_path: str) -> None:
        relative = unquote(request_path.lstrip("/") or "index.html")
        candidate = (FRONTEND_ROOT / relative).resolve()
        if not str(candidate).startswith(str(FRONTEND_ROOT.resolve())):
            self._send_json({"error": "Invalid path."}, HTTPStatus.BAD_REQUEST)
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._headers(content_type)
        if relative in ("sw.js",):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(candidate.read_bytes())

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

    def _read_raw_body(self) -> bytes | None:
        length = int(self.headers.get("Content-Length", "0"))
        if length > self.MAX_BODY_SIZE:
            self._send_json({"error": "Request body too large. Max 10 MB."}, HTTPStatus.BAD_REQUEST)
            return None
        if length <= 0:
            return b"{}"
        return self.rfile.read(length)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
        self.send_response(status)
        self._headers("application/json")
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._headers("text/plain")
        self.end_headers()

    def _headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        apply_cors_headers(self)
        apply_security_headers(self)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def run(host: str = "0.0.0.0", port: int = 8765) -> None:
    try:
        from .database import DBConfig, init_pool
        init_pool(DBConfig.from_env())
        print("Database pool initialized.")
    except Exception as exc:
        logger.warning("Database not available (%s). Running without persistence.", exc)

    allowed_origins = os.environ.get("HP_CORS_ORIGINS", "").split(",")
    allowed_origins = [o.strip() for o in allowed_origins if o.strip()]
    if allowed_origins:
        from .middleware import set_allowed_origins
        set_allowed_origins(allowed_origins)
        print(f"CORS restricted to: {allowed_origins}")
    else:
        print("CORS: All origins allowed (set HP_CORS_ORIGINS to restrict)")

    init_audit_logger()

    server = ThreadingHTTPServer((host, port), HumanProofHandler)
    print(f"Mr Money AI running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_audit_logger()
        try:
            from .database import close_pool
            close_pool()
        except Exception as exc:
            logger.warning("Failed to close database pool: %s", exc)


# ---------------------------------------------------------------------------
# Auto-format and humanization helpers
# ---------------------------------------------------------------------------

def _auto_format(text: str) -> str:
    """Apply basic auto-formatting rules to text."""
    import re as _re
    lines = text.split("\n")
    result: list[str] = []
    prev_blank = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if not prev_blank:
                result.append("")
                prev_blank = True
            continue
        prev_blank = False
        stripped = _re.sub(r"\s+", " ", stripped)
        stripped = _re.sub(r"\s+([.,;:!?])", r"\1", stripped)
        stripped = _re.sub(r"\(\s+", "(", stripped)
        stripped = _re.sub(r"\s+\)", ")", stripped)
        result.append(stripped)
    return "\n\n".join(result)


def _humanize_text(text: str, mode: str = "professional") -> dict:
    """Apply rule-based humanization improvements while preserving meaning."""
    import re as _re
    original = text
    changes: list[dict] = []
    improved = text

    passive_patterns = [
        (r"\bwas\s+(\w+ed)\b", r"actively \1"),
        (r"\bare\s+(\w+ed)\b", r"actively \1"),
    ]
    for pattern, replacement in passive_patterns:
        for match in _re.finditer(pattern, improved, _re.I):
            changes.append({
                "type": "passive_voice",
                "original": match.group(),
                "suggested": _re.sub(pattern, replacement, match.group(), count=1),
            })

    filler_words = ["very", "really", "quite", "basically", "actually", "just", "simply"]
    for filler in filler_words:
        pattern = r"\b" + filler + r"\b"
        matches = list(_re.finditer(pattern, improved, _re.I))
        for match in matches[:2]:
            changes.append({
                "type": "filler_word",
                "original": match.group(),
                "suggested": "",
            })

    wordiness = {
        "due to the fact that": "because",
        "in order to": "to",
        "at this point in time": "now",
        "in the event that": "if",
        "for the purpose of": "to",
        "it is important to note that": "",
        "with regard to": "about",
        "in terms of": "for",
    }
    for phrase, replacement in wordiness.items():
        if phrase in improved.lower():
            pattern = _re.compile(_re.escape(phrase), _re.I)
            match = pattern.search(improved)
            if match:
                changes.append({
                    "type": "wordiness",
                    "original": match.group(),
                    "suggested": replacement,
                })

    return {
        "original": original,
        "improved": improved,
        "changes": changes,
        "changeCount": len(changes),
        "mode": mode,
        "message": f"Found {len(changes)} improvement(s). Apply suggestions to improve readability.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Mr Money AI local API server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run(args.host, args.port)


if __name__ == "__main__":
    main()
