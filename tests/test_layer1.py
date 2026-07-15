"""Tests for Layer 1 modifications: middleware, rbac, auth, memory, collaboration, webhooks, search, reports, extractors."""

import hashlib
import os
import secrets
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ["HP_JWT_SECRET"] = "test-secret-key-for-unit-tests-32chars!!"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from humanproof.middleware import (
    MiddlewareResult,
    apply_cors_headers,
    apply_security_headers,
    authenticate_request,
    check_rate_limit,
    generate_csrf_token,
    generate_request_id,
    run_middleware,
    sanitize_filename,
    validate_csrf_token,
    validate_json_body,
    set_allowed_origins,
    lock_origins,
    _check_json_depth,
)
from humanproof.rbac import (
    ROLE_INHERITANCE,
    Permission,
    Role,
    get_permissions_for_role,
    get_roles_with_permission,
    has_permission,
    has_scope_permission,
)
from humanproof.auth import (
    JWT_ISSUER,
    _is_strong_password,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    is_token_blacklisted,
    verify_api_key,
)
import humanproof.auth as _auth
if not _auth.JWT_SECRET or len(_auth.JWT_SECRET) < 10:
    _auth.JWT_SECRET = os.environ.get("HP_JWT_SECRET", "test-secret-key-for-unit-tests-32ch!")
from humanproof.memory import ConversationMemory
from humanproof.collaboration import CollaborationManager
from humanproof.webhooks import WebhookManager
from humanproof.search import web_search, _search_cache, _cache_key
from humanproof.reports import (
    export_report,
    get_chart_data,
    report_as_csv,
    report_as_json,
    report_as_html,
)
from humanproof.orchestrator import review_text


# ---------------------------------------------------------------------------
# Middleware Tests
# ---------------------------------------------------------------------------

class MiddlewareTests(unittest.TestCase):
    def test_generate_request_id_unique(self):
        id1 = generate_request_id()
        id2 = generate_request_id()
        self.assertNotEqual(id1, id2)
        self.assertEqual(len(id1), 16)

    def test_csrf_token_roundtrip(self):
        token = generate_csrf_token("session1")
        self.assertTrue(validate_csrf_token(token))
        self.assertFalse(validate_csrf_token("invalid-token"))

    def test_csrf_token_reuse_prevented(self):
        token = generate_csrf_token("session1")
        self.assertTrue(validate_csrf_token(token))
        self.assertFalse(validate_csrf_token(token))

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("hello.txt"), "hello.txt")
        self.assertNotIn("..", sanitize_filename("../etc/passwd"))
        self.assertNotIn("<", sanitize_filename('<script>alert("xss")</script>.txt'))
        self.assertEqual(sanitize_filename(""), "upload.txt")

    def test_validate_json_body_valid(self):
        data, err = validate_json_body(b'{"key": "value"}')
        self.assertIsNone(err)
        self.assertEqual(data, {"key": "value"})

    def test_validate_json_body_empty(self):
        data, err = validate_json_body(b"{}")
        self.assertIsNone(err)
        self.assertEqual(data, {})

    def test_validate_json_body_invalid(self):
        data, err = validate_json_body(b"not json")
        self.assertIsNotNone(err)
        self.assertIsNone(data)

    def test_validate_json_body_non_dict(self):
        data, err = validate_json_body(b'[1,2,3]')
        self.assertIsNotNone(err)

    def test_check_json_depth_ok(self):
        nested = {"a": {"b": {"c": 1}}}
        self.assertTrue(_check_json_depth(nested))

    def test_check_json_depth_too_deep(self):
        obj = {}
        current = obj
        for _ in range(15):
            current["next"] = {}
            current = current["next"]
        self.assertFalse(_check_json_depth(obj))

    def test_rate_limit(self):
        key = f"test_ratelimit_{secrets.token_hex(4)}"
        for _ in range(5):
            self.assertTrue(check_rate_limit(key, max_requests=5, window_seconds=60))
        self.assertFalse(check_rate_limit(key, max_requests=5, window_seconds=60))

    def test_cors_headers_allow_origin(self):
        handler = MagicMock()
        handler.headers = {"Origin": "https://example.com"}
        set_allowed_origins(["https://example.com"])
        apply_cors_headers(handler)
        calls = {call[0][0]: call[0][1] for call in handler.send_header.call_args_list}
        self.assertEqual(calls.get("Access-Control-Allow-Origin"), "https://example.com")
        set_allowed_origins([])
        lock_origins()

    def test_security_headers(self):
        handler = MagicMock()
        handler.headers = {}
        apply_security_headers(handler)
        calls = {call[0][0]: call[0][1] for call in handler.send_header.call_args_list}
        self.assertEqual(calls.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(calls.get("X-Frame-Options"), "DENY")
        self.assertIn("max-age=31536000", calls.get("Strict-Transport-Security", ""))
        self.assertNotIn("unsafe-eval", calls.get("Content-Security-Policy", ""))


# ---------------------------------------------------------------------------
# RBAC Tests
# ---------------------------------------------------------------------------

class RBACTests(unittest.TestCase):
    def test_role_inheritance(self):
        self.assertIn(Role.REVIEWER, ROLE_INHERITANCE[Role.EDITOR])
        self.assertIn(Role.VIEWER, ROLE_INHERITANCE[Role.REVIEWER])
        self.assertIn(Role.ADMIN, ROLE_INHERITANCE[Role.ORG_ADMIN])

    def test_get_permissions_for_role_includes_inherited(self):
        editor_perms = get_permissions_for_role(Role.EDITOR)
        self.assertIn(Permission.READ, editor_perms)
        self.assertIn(Permission.WRITE, editor_perms)
        self.assertIn(Permission.REVIEW, editor_perms)
        self.assertIn(Permission.MANAGE_WORKSPACE, editor_perms)

    def test_get_roles_with_permission(self):
        roles = get_roles_with_permission(Permission.MANAGE_USERS)
        self.assertIn(Role.ADMIN, roles)
        self.assertIn(Role.ORG_ADMIN, roles)
        self.assertNotIn(Role.VIEWER, roles)

    def test_has_permission(self):
        self.assertTrue(has_permission(["read", "write"], Permission.READ))
        self.assertFalse(has_permission(["read"], Permission.WRITE))

    def test_has_scope_permission(self):
        perms = {"read", "write:doc123"}
        self.assertTrue(has_scope_permission(perms, "doc123", Permission.WRITE))
        self.assertTrue(has_scope_permission(perms, "anything", Permission.READ))
        self.assertFalse(has_scope_permission(perms, "doc456", Permission.WRITE))


# ---------------------------------------------------------------------------
# Auth Tests
# ---------------------------------------------------------------------------

class AuthTests(unittest.TestCase):
    def test_password_strength_weak(self):
        ok, msg = _is_strong_password("short")
        self.assertFalse(ok)
        self.assertIn("at least", msg)

    def test_password_strength_no_uppercase(self):
        ok, msg = _is_strong_password("alllowercase1!")
        self.assertFalse(ok)
        self.assertIn("uppercase", msg)

    def test_password_strength_no_digit(self):
        ok, msg = _is_strong_password("NoDigitHere!")
        self.assertFalse(ok)
        self.assertIn("digit", msg)

    def test_password_strength_strong(self):
        ok, msg = _is_strong_password("StrongP@ss1")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_token_blacklist(self):
        token_id = secrets.token_hex(8)
        self.assertFalse(is_token_blacklisted(token_id))
        blacklist_token(token_id)
        self.assertTrue(is_token_blacklisted(token_id))

    def test_create_and_decode_access_token(self):
        token = create_access_token("user1", "org1", ["read", "write"])
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "user1")
        self.assertEqual(payload["org"], "org1")
        self.assertIn("read", payload["perms"])
        self.assertIn("jti", payload)
        self.assertEqual(payload["iss"], JWT_ISSUER)
        self.assertEqual(payload["aud"], "org1")

    def test_decode_blacklisted_token(self):
        token = create_access_token("user1", "org1", ["read"])
        payload = decode_token(token)
        token_id = payload["jti"]
        blacklist_token(token_id)
        self.assertIsNone(decode_token(token))

    def test_create_refresh_token(self):
        token = create_refresh_token("user1", "org1")
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "refresh")
        self.assertIn("jti", payload)
        self.assertEqual(payload["iss"], JWT_ISSUER)

    def test_api_key_roundtrip(self):
        raw_key, key_hash = generate_api_key()
        self.assertTrue(raw_key.startswith("mm_"))
        self.assertTrue(verify_api_key(raw_key, key_hash))
        self.assertFalse(verify_api_key("wrong_key", key_hash))


# ---------------------------------------------------------------------------
# Memory Tests
# ---------------------------------------------------------------------------

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.user_id = f"test_user_{secrets.token_hex(4)}"
        self.memory = ConversationMemory(self.user_id, ttl_seconds=86400)

    def tearDown(self):
        file = self.memory._file
        if file.exists():
            file.unlink()

    def test_add_and_search(self):
        entry = self.memory.add("I prefer dark mode", "preference")
        self.assertEqual(entry.category, "preference")
        results = self.memory.search("dark mode")
        self.assertTrue(len(results) >= 1)

    def test_deduplication(self):
        e1 = self.memory.add("I prefer dark mode", "preference")
        e2 = self.memory.add("I prefer dark mode", "preference")
        self.assertEqual(e1.id, e2.id)
        stats = self.memory.get_stats()
        self.assertEqual(stats["total"], 1)

    def test_update_content(self):
        entry = self.memory.add("Old content", "fact")
        self.assertTrue(self.memory.update_content(entry.id, "New content"))
        results = self.memory.search("New content")
        self.assertTrue(any(e.content == "New content" for e in results))

    def test_delete(self):
        entry = self.memory.add("To be deleted", "fact")
        self.assertTrue(self.memory.delete(entry.id))
        self.assertFalse(self.memory.delete(entry.id))

    def test_ttl_expiry(self):
        memory = ConversationMemory(f"ttl_user_{secrets.token_hex(4)}", ttl_seconds=86400)
        memory.add("Ephemeral fact", "fact", ttl_seconds=1)
        self.assertEqual(memory.get_stats()["total"], 1)
        time.sleep(1.1)
        memory._purge_expired()
        self.assertEqual(memory.get_stats()["total"], 0)
        memory._file.unlink(missing_ok=True)

    def test_auto_extract(self):
        entries = self.memory.auto_extract("I prefer the morning schedule for meetings.")
        self.assertTrue(len(entries) >= 1)
        self.assertEqual(entries[0].category, "preference")


# ---------------------------------------------------------------------------
# Collaboration Tests
# ---------------------------------------------------------------------------

class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.mgr = CollaborationManager()

    def test_add_comment(self):
        comment = self.mgr.add_comment("doc1", "user1", "Alice", "Looks good!")
        self.assertEqual(comment.document_id, "doc1")
        self.assertEqual(comment.author_name, "Alice")
        self.assertEqual(comment.status, "open")

    def test_reply_to_comment(self):
        parent = self.mgr.add_comment("doc1", "user1", "Alice", "Question here?")
        reply = self.mgr.reply_to_comment("doc1", parent.id, "user2", "Bob", "Answer!")
        self.assertIsNotNone(reply)
        self.assertEqual(reply.parent_id, parent.id)
        self.assertIn(reply, parent.replies)

    def test_reply_to_nonexistent_comment(self):
        result = self.mgr.reply_to_comment("doc1", "nonexistent", "user1", "Alice", "Nope")
        self.assertIsNone(result)

    def test_resolve_comment(self):
        comment = self.mgr.add_comment("doc1", "user1", "Alice", "Fix this")
        self.assertTrue(self.mgr.resolve_comment(comment.id))
        self.assertEqual(comment.status, "resolved")
        self.assertIsNotNone(comment.resolved_at)

    def test_workflow_with_due_dates(self):
        reviewers = [{"id": "r1", "name": "Reviewer 1"}]
        workflow = self.mgr.create_workflow("doc1", "Test Workflow", reviewers)
        self.assertEqual(workflow.status, "pending")
        step = workflow.steps[0]
        self.assertEqual(step.status, "pending")

    def test_decide_step(self):
        reviewers = [{"id": "r1", "name": "Reviewer 1"}]
        workflow = self.mgr.create_workflow("doc1", "Test Workflow", reviewers)
        result = self.mgr.decide_step(workflow.id, workflow.steps[0].id, "approved", "r1")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "approved")


# ---------------------------------------------------------------------------
# Webhook Tests
# ---------------------------------------------------------------------------

class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.mgr = WebhookManager()

    def test_create_subscription(self):
        sub = self.mgr.create_subscription("org1", "https://example.com/hook", ["review.completed"])
        self.assertEqual(sub.org_id, "org1")
        self.assertTrue(sub.enabled)
        self.assertEqual(len(sub.signing_secret), 64)

    def test_remove_subscription(self):
        sub = self.mgr.create_subscription("org1", "https://example.com/hook", ["review.completed"])
        self.assertTrue(self.mgr.remove_subscription(sub.id))
        self.assertFalse(self.mgr.remove_subscription(sub.id))

    def test_list_subscriptions(self):
        self.mgr.create_subscription("org1", "https://example.com/hook1", ["review.completed"])
        self.mgr.create_subscription("org2", "https://example.com/hook2", ["document.uploaded"])
        org1_subs = self.mgr.list_subscriptions("org1")
        self.assertEqual(len(org1_subs), 1)

    def test_delivery_stats(self):
        stats = self.mgr.get_delivery_stats("org1")
        self.assertIn("total", stats)
        self.assertIn("delivered", stats)
        self.assertIn("failed", stats)
        self.assertIn("success_rate", stats)

    def test_emit_event_creates_delivery(self):
        self.mgr.create_subscription("org1", "https://example.com/hook", ["review.completed"])
        self.mgr.emit_event("org1", "review.completed", {"doc_id": "123"})
        self.assertEqual(len(self.mgr._deliveries), 1)


# ---------------------------------------------------------------------------
# Search Cache Tests
# ---------------------------------------------------------------------------

class SearchCacheTests(unittest.TestCase):
    def test_cache_key_deterministic(self):
        k1 = _cache_key("test query", 5)
        k2 = _cache_key("test query", 5)
        self.assertEqual(k1, k2)

    def test_cache_key_different_queries(self):
        k1 = _cache_key("query one", 5)
        k2 = _cache_key("query two", 5)
        self.assertNotEqual(k1, k2)


# ---------------------------------------------------------------------------
# Reports Tests
# ---------------------------------------------------------------------------

class ReportExtendedTests(unittest.TestCase):
    def setUp(self):
        self.report = review_text(
            "This is a concise report about policy changes. References\nSmith (2024). "
            "The implementation was carried out by trained staff.",
            "report_extended.txt",
        )

    def test_csv_export(self):
        data = report_as_csv(self.report)
        self.assertIn(b"Category", data)
        self.assertIn(b"Severity", data)

    def test_chart_data(self):
        chart = get_chart_data(self.report)
        self.assertIn("scores", chart)
        self.assertIn("severity_distribution", chart)
        self.assertIn("total_findings", chart)
        self.assertIsInstance(chart["scores"], dict)

    def test_html_export(self):
        data = report_as_html(self.report)
        self.assertIn(b"<!doctype html>", data)
        self.assertIn(b"Mr Money AI", data)

    def test_csv_in_export_report(self):
        data, ct, ext = export_report(self.report, "csv")
        self.assertEqual(ct, "text/csv")
        self.assertEqual(ext, "csv")

    def test_export_unsupported_format(self):
        with self.assertRaises(ValueError):
            export_report(self.report, "xyz")


# ---------------------------------------------------------------------------
# Extractor Tests (extended)
# ---------------------------------------------------------------------------

class ExtractorExtendedTests(unittest.TestCase):
    def test_html_extraction_with_bs4(self):
        from humanproof.extractors import extract_document
        html = b"<html><head><style>.red{}</style></head><body><h1>Title</h1><p>Hello world.</p></body></html>"
        doc = extract_document(html, "test.html", "text/html")
        self.assertIn("Title", doc.text)
        self.assertIn("Hello world.", doc.text)

    def test_csv_extraction(self):
        from humanproof.extractors import extract_document
        csv_data = b"Name,Age\nAlice,30\nBob,25"
        doc = extract_document(csv_data, "data.csv", "text/csv")
        self.assertIn("Alice", doc.text)
        self.assertIn("Bob", doc.text)


if __name__ == "__main__":
    unittest.main()
