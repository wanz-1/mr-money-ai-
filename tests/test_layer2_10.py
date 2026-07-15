"""Tests for Layers 2-10: new modules, orchestrator pipeline, cache, logging, auth MFA."""

import os
import sys
import time
import secrets
import unittest
from unittest.mock import MagicMock

os.environ["HP_JWT_SECRET"] = "test-secret-key-for-unit-tests-32chars!!"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from humanproof.models import Finding, AgentResult, TextSpan, DocumentMetadata, VALID_SEVERITIES
from humanproof.models import Document


class ModelValidationTests(unittest.TestCase):
    def test_finding_severity_clamped(self):
        f = Finding("grammar", "HIGH", "title", "msg", "rec", 0.9, "agent")
        self.assertEqual(f.severity, "high")

    def test_finding_invalid_severity_raises(self):
        with self.assertRaises(ValueError):
            Finding("grammar", "invalid", "title", "msg", "rec", 0.5, "agent")

    def test_finding_confidence_clamped(self):
        f = Finding("grammar", "info", "title", "msg", "rec", 5.0, "agent")
        self.assertEqual(f.confidence, 1.0)
        f2 = Finding("grammar", "info", "title", "msg", "rec", -1.0, "agent")
        self.assertEqual(f2.confidence, 0.0)

    def test_finding_empty_category_raises(self):
        with self.assertRaises(ValueError):
            Finding("", "info", "title", "msg", "rec", 0.5, "agent")

    def test_text_span_start_gt_end_raises(self):
        with self.assertRaises(ValueError):
            TextSpan(start=10, end=5)

    def test_document_metadata_negative_size_raises(self):
        with self.assertRaises(ValueError):
            DocumentMetadata(size_bytes=-1)

    def test_agent_result_metrics_clamped(self):
        ar = AgentResult("agent", "summary", {"score": 150.0})
        self.assertEqual(ar.metrics["score"], 100.0)


from humanproof.compliance import (
    ComplianceEngine, LegalBasis, PIICategory, ConsentRecord,
    DPIA, DataRetentionPolicy, detect_pii, redact_pii, pseudonymize,
)


class ComplianceTests(unittest.TestCase):
    def test_detect_pii_email(self):
        pii = detect_pii("Contact me at test@example.com")
        self.assertIn(PIICategory.EMAIL, pii)
        self.assertEqual(pii[PIICategory.EMAIL], ["test@example.com"])

    def test_detect_pii_phone(self):
        pii = detect_pii("Call 555-123-4567 today")
        self.assertIn(PIICategory.PHONE, pii)

    def test_detect_pii_ssn(self):
        pii = detect_pii("SSN: 123-45-6789")
        self.assertIn(PIICategory.SSN, pii)

    def test_redact_pii(self):
        text = "Email me at a@b.com or call 555-123-4567"
        redacted = redact_pii(text)
        self.assertNotIn("a@b.com", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_pseudonymize_deterministic(self):
        p1 = pseudonymize("john@example.com")
        p2 = pseudonymize("john@example.com")
        self.assertEqual(p1, p2)
        self.assertTrue(p1.startswith("pseudo_"))

    def test_consent_lifecycle(self):
        engine = ComplianceEngine()
        rec = engine.record_consent("user1", "analytics")
        self.assertTrue(rec.is_active)
        engine.revoke_consent(rec.id)
        self.assertFalse(rec.is_active)

    def test_has_active_consent(self):
        engine = ComplianceEngine()
        engine.record_consent("user1", "analytics")
        self.assertTrue(engine.has_active_consent("user1", "analytics"))
        self.assertFalse(engine.has_active_consent("user1", "marketing"))

    def test_dpia_risk_levels(self):
        dpia = DPIA()
        r1 = dpia.add_risk("Data breach", "high", "high")
        self.assertEqual(r1["risk_level"], "critical")
        r2 = dpia.add_risk("Minor issue", "low", "low")
        self.assertEqual(r2["risk_level"], "low")

    def test_check_document_compliance_clean(self):
        engine = ComplianceEngine()
        result = engine.check_document_compliance("This is a clean document.")
        self.assertTrue(result["compliant"])

    def test_check_document_compliance_pii(self):
        engine = ComplianceEngine()
        result = engine.check_document_compliance("Email: test@example.com")
        self.assertFalse(result["compliant"])
        self.assertTrue(result["total_issues"] > 0)

    def test_retention_policy_expiry(self):
        from datetime import datetime, timedelta, timezone
        policy = DataRetentionPolicy(retention_days=30)
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        self.assertTrue(policy.is_expired(old))
        recent = datetime.now(timezone.utc).isoformat()
        self.assertFalse(policy.is_expired(recent))


from humanproof.integrations import (
    IntegrationManager, CircuitBreaker, CircuitState,
    generate_hmac_signature, verify_hmac_signature, IntegrationStatus,
)


class IntegrationTests(unittest.TestCase):
    def test_circuit_breaker_opens(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
        for _ in range(3):
            cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.allow_request())

    def test_circuit_breaker_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        time.sleep(0.15)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        self.assertTrue(cb.allow_request())

    def test_circuit_breaker_reset(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_hmac_signature_roundtrip(self):
        payload = b'{"event": "test"}'
        sig = generate_hmac_signature(payload, "secret123")
        self.assertTrue(verify_hmac_signature(payload, sig))

    def test_hmac_signature_wrong_payload(self):
        payload = b'{"event": "test"}'
        sig = generate_hmac_signature(payload, "secret123")
        self.assertFalse(verify_hmac_signature(b'{"event": "other"}', sig))

    def test_hmac_signature_expired(self):
        payload = b'{"event": "test"}'
        sig = generate_hmac_signature(payload, "secret123", timestamp="2020-01-01T00:00:00Z")
        self.assertFalse(verify_hmac_signature(payload, sig, tolerance_seconds=10))

    def test_integration_lifecycle(self):
        mgr = IntegrationManager()
        conn = mgr.connect("org1", "slack", "My Slack")
        self.assertEqual(conn.status, IntegrationStatus.ACTIVE)
        self.assertTrue(mgr.disconnect(conn.id))
        self.assertFalse(mgr.disconnect(conn.id))

    def test_list_connections(self):
        mgr = IntegrationManager()
        mgr.connect("org1", "slack", "S1")
        mgr.connect("org1", "github", "G1")
        mgr.connect("org2", "slack", "S2")
        self.assertEqual(len(mgr.list_connections("org1")), 2)
        self.assertEqual(len(mgr.list_connections("org2")), 1)

    def test_send_request_connection_not_found(self):
        mgr = IntegrationManager()
        result = mgr.send_request("nonexistent", "http://example.com")
        self.assertEqual(result["error"], "connection_not_found")


from humanproof.knowledge import KnowledgeBase, extract_keywords, chunk_text


class KnowledgeTests(unittest.TestCase):
    def test_extract_keywords(self):
        kw = extract_keywords("the quick brown fox jumps over the lazy dog", top_n=3)
        self.assertNotIn("the", kw)
        self.assertIn("quick", kw)

    def test_chunk_text_short(self):
        chunks = chunk_text("short text", chunk_size=100)
        self.assertEqual(len(chunks), 1)

    def test_chunk_text_long(self):
        text = " ".join(["word"] * 200)
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        self.assertTrue(len(chunks) > 1)

    def test_add_and_search(self):
        kb = KnowledgeBase(default_ttl_seconds=86400)
        entry = kb.add_entry("org1", "Python Guide", "Python is a programming language used for data science and web development.")
        results = kb.search("org1", "python programming")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].entry_id, entry.id)

    def test_crud(self):
        kb = KnowledgeBase()
        entry = kb.add_entry("org1", "Title", "Content here")
        self.assertIsNotNone(kb.get_entry(entry.id))
        self.assertTrue(kb.update_entry(entry.id, title="Updated"))
        self.assertEqual(kb.get_entry(entry.id).title, "Updated")
        self.assertTrue(kb.delete_entry(entry.id))
        self.assertIsNone(kb.get_entry(entry.id))

    def test_ttl_expiry(self):
        kb = KnowledgeBase()
        entry = kb.add_entry("org1", "Ephemeral", "Content", ttl_seconds=1)
        self.assertIsNotNone(kb.get_entry(entry.id))
        time.sleep(1.1)
        self.assertIsNone(kb.get_entry(entry.id))

    def test_stats(self):
        kb = KnowledgeBase()
        kb.add_entry("org1", "A", "Content A", category="docs")
        kb.add_entry("org1", "B", "Content B", category="faq")
        stats = kb.stats("org1")
        self.assertEqual(stats["total_entries"], 2)
        self.assertEqual(stats["categories"]["docs"], 1)


from humanproof.style_guide import StyleGuide, Tone, TONE_PRESETS


class StyleGuideTests(unittest.TestCase):
    def test_add_and_remove_term(self):
        sg = StyleGuide()
        t = sg.add_term("utilize", preferred="use")
        self.assertEqual(len(sg.list_terms()), 1)
        sg.remove_term(t.id)
        self.assertEqual(len(sg.list_terms()), 0)

    def test_add_and_remove_rule(self):
        sg = StyleGuide()
        r = sg.add_rule("No exclamation", pattern=r"!", severity="low")
        self.assertEqual(len(sg.list_rules()), 1)
        sg.remove_rule(r.id)
        self.assertEqual(len(sg.list_rules()), 0)

    def test_check_formal_contraction(self):
        sg = StyleGuide(default_tone=Tone.FORMAL)
        result = sg.check_document("I can't believe it. We won't fail.")
        self.assertTrue(any(v.rule_id == "tone_contraction" for v in result.violations))

    def test_check_formal_filler(self):
        sg = StyleGuide(default_tone=Tone.TECHNICAL)
        result = sg.check_document("This is very really good work.")
        filler_violations = [v for v in result.violations if v.rule_id == "tone_avoid_word"]
        self.assertTrue(len(filler_violations) >= 1)

    def test_check_term_suggestions(self):
        sg = StyleGuide()
        sg.add_term("utilize", preferred="use")
        result = sg.check_document("We should utilize this method.")
        self.assertTrue(len(result.term_suggestions) > 0)
        self.assertEqual(result.term_suggestions[0]["preferred"], "use")

    def test_score_starts_at_100(self):
        sg = StyleGuide(default_tone=Tone.INFORMAL)
        result = sg.check_document("Clean document with no issues.")
        self.assertEqual(result.score, 100.0)

    def test_tone_detection(self):
        sg = StyleGuide()
        result = sg.check_document("The implementation leverages algorithmic optimization.")
        self.assertIn(result.tone_detected, ["formal", "technical", "business", "academic"])


from humanproof.orchestrator import (
    review_text, review_document, ReviewPipeline, PipelineState,
)


class OrchestratorPipelineTests(unittest.TestCase):
    def test_parallel_review(self):
        report = review_text(
            "This document tests parallel review. The program was implemented correctly.",
            "parallel.txt", parallel=True, max_workers=2
        )
        self.assertIn("publication_readiness", report.scores)
        self.assertTrue(report.findings)

    def test_sequential_review_still_works(self):
        report = review_text("Simple test document for sequential review.", "seq.txt")
        self.assertIn("publication_readiness", report.scores)

    def test_progress_callback(self):
        calls = []
        def cb(name, done, total, status):
            calls.append((name, done, total, status))
        report = review_text("Test with callback.", "cb.txt", progress_callback=cb)
        self.assertTrue(len(calls) > 0)

    def test_pipeline_state_machine(self):
        doc = Document(text="Test.", metadata=DocumentMetadata())
        pipeline = ReviewPipeline(doc, max_workers=2)
        self.assertEqual(pipeline.state, PipelineState.PENDING)
        report = pipeline.run()
        self.assertIn(pipeline.state, (PipelineState.COMPLETE, PipelineState.PARTIAL))
        self.assertIn("publication_readiness", report.scores)


from humanproof.cache import (
    TTLCache, cache_doc_hash, get_cached_doc_hash,
    should_reanalyze, cache_stats, purge_all_expired,
    compute_content_hash,
)


class CacheTests(unittest.TestCase):
    def test_ttl_cache_put_get(self):
        cache = TTLCache(max_size=10, default_ttl=60)
        cache.put("k1", "v1")
        self.assertEqual(cache.get("k1"), "v1")

    def test_ttl_cache_expiry(self):
        cache = TTLCache(max_size=10, default_ttl=0.1)
        cache.put("k1", "v1")
        time.sleep(0.15)
        self.assertIsNone(cache.get("k1"))

    def test_ttl_cache_lru_eviction(self):
        cache = TTLCache(max_size=2, default_ttl=60)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")
        self.assertIsNone(cache.get("k1"))
        self.assertEqual(cache.get("k3"), "v3")

    def test_ttl_cache_invalidate(self):
        cache = TTLCache()
        cache.put("k1", "v1")
        self.assertTrue(cache.invalidate("k1"))
        self.assertFalse(cache.invalidate("k1"))

    def test_ttl_cache_stats(self):
        cache = TTLCache()
        cache.put("k1", "v1")
        cache.get("k1")
        cache.get("missing")
        stats = cache.stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_domain_caches(self):
        cache_doc_hash("doc1", "hash1")
        self.assertEqual(get_cached_doc_hash("doc1"), "hash1")
        self.assertFalse(should_reanalyze("doc1", "hash1"))
        self.assertTrue(should_reanalyze("doc1", "hash2"))

    def test_compute_content_hash(self):
        h1 = compute_content_hash(b"hello")
        h2 = compute_content_hash(b"hello")
        self.assertEqual(h1, h2)
        h3 = compute_content_hash(b"world")
        self.assertNotEqual(h1, h3)


from humanproof.logging_config import (
    MetricsCollector, Timer, timed, begin_request, end_request,
    setup_logging, StructuredFormatter,
)


class LoggingTests(unittest.TestCase):
    def test_metrics_collector_singleton(self):
        m1 = MetricsCollector()
        m2 = MetricsCollector()
        self.assertIs(m1, m2)

    def test_metrics_increment(self):
        m = MetricsCollector()
        m.reset()
        m.increment("test.counter")
        m.increment("test.counter")
        snap = m.snapshot()
        self.assertEqual(snap["counters"]["test.counter"], 2)

    def test_metrics_record_time(self):
        m = MetricsCollector()
        m.reset()
        m.record_time("test.timer", 100.0)
        m.record_time("test.timer", 200.0)
        snap = m.snapshot()
        self.assertEqual(snap["timers"]["test.timer"]["count"], 2)
        self.assertEqual(snap["timers"]["test.timer"]["avg_ms"], 150.0)

    def test_metrics_gauge(self):
        m = MetricsCollector()
        m.reset()
        m.set_gauge("test.gauge", 42.0)
        snap = m.snapshot()
        self.assertEqual(snap["gauges"]["test.gauge"], 42.0)

    def test_timer_context_manager(self):
        with Timer("test_timer") as t:
            time.sleep(0.01)
        self.assertTrue(t.elapsed_ms > 0)

    def test_timed_decorator(self):
        @timed("decorated_func")
        def func():
            return 42
        result = func()
        self.assertEqual(result, 42)

    def test_begin_end_request(self):
        rid = begin_request()
        self.assertEqual(len(rid), 16)
        end_request(200, 10.0)
        end_request(404, 5.0)
        m = MetricsCollector()
        snap = m.snapshot()
        self.assertIn("requests.200", snap["counters"])
        self.assertIn("requests.404", snap["counters"])


from humanproof.auth import (
    generate_mfa_secret, generate_mfa_code, verify_mfa_code, generate_mfa_uri,
)


class MFATests(unittest.TestCase):
    def test_secret_generation(self):
        secret = generate_mfa_secret()
        self.assertGreaterEqual(len(secret), 20)
        import base64
        padded = secret + "=" * ((8 - len(secret) % 8) % 8)
        base64.b32decode(padded)

    def test_code_generation(self):
        secret = generate_mfa_secret()
        code = generate_mfa_code(secret)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_verify_code(self):
        secret = generate_mfa_secret()
        code = generate_mfa_code(secret)
        self.assertTrue(verify_mfa_code(secret, code))

    def test_verify_wrong_code(self):
        secret = generate_mfa_secret()
        self.assertFalse(verify_mfa_code(secret, "000000"))

    def test_generate_uri(self):
        secret = generate_mfa_secret()
        uri = generate_mfa_uri(secret, "user@example.com")
        self.assertIn("otpauth://totp/", uri)
        self.assertIn("secret=" + secret, uri)


if __name__ == "__main__":
    unittest.main()
