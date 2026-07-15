"""Compliance, privacy, and regulatory framework for Mr Money AI.

Provides GDPR data-retention enforcement, DPIA templates,
consent tracking, and PII redaction utilities.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class LegalBasis(str, Enum):
    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"
    LEGITIMATE_INTERESTS = "legitimate_interests"


class PIICategory(str, Enum):
    NAME = "name"
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    ADDRESS = "address"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    DATE_OF_BIRTH = "date_of_birth"
    MEDICAL = "medical"
    FINANCIAL = "financial"


@dataclass
class ConsentRecord:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str = ""
    purpose: str = ""
    legal_basis: LegalBasis = LegalBasis.CONSENT
    granted: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        if not self.granted:
            return False
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            from datetime import datetime as _dt
            try:
                exp = _dt.fromisoformat(self.expires_at)
                if _dt.now(timezone.utc) > exp:
                    return False
            except (ValueError, TypeError):
                pass
        return True

    def revoke(self) -> None:
        self.granted = False
        self.revoked_at = datetime.now(timezone.utc).isoformat()


@dataclass
class DPIA:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    title: str = ""
    description: str = ""
    data_categories: List[str] = field(default_factory=list)
    processing_purposes: List[str] = field(default_factory=list)
    legal_basis: LegalBasis = LegalBasis.LEGITIMATE_INTERESTS
    risks: List[Dict[str, Any]] = field(default_factory=list)
    mitigations: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "draft"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewer: str = ""

    def add_risk(self, description: str, likelihood: str, impact: str) -> Dict[str, Any]:
        risk = {
            "id": uuid.uuid4().hex[:8],
            "description": description,
            "likelihood": likelihood,
            "impact": impact,
            "risk_level": self._compute_risk_level(likelihood, impact),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.risks.append(risk)
        return risk

    def add_mitigation(self, risk_id: str, description: str, owner: str) -> Dict[str, Any]:
        mitigation = {
            "id": uuid.uuid4().hex[:8],
            "risk_id": risk_id,
            "description": description,
            "owner": owner,
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.mitigations.append(mitigation)
        return mitigation

    def risk_summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self.risks:
            level = r.get("risk_level", "unknown")
            counts[level] = counts.get(level, 0) + 1
        return counts

    @staticmethod
    def _compute_risk_level(likelihood: str, impact: str) -> str:
        levels = {"low": 1, "medium": 2, "high": 3}
        l = levels.get(likelihood.lower(), 1)
        i = levels.get(impact.lower(), 1)
        score = l * i
        if score >= 6:
            return "critical"
        if score >= 4:
            return "high"
        if score >= 2:
            return "medium"
        return "low"


@dataclass
class DataRetentionPolicy:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    data_category: str = ""
    retention_days: int = 365
    auto_delete: bool = False
    legal_basis: LegalBasis = LegalBasis.LEGITIMATE_INTERESTS
    description: str = ""

    def is_expired(self, created_at_iso: str) -> bool:
        try:
            created = datetime.fromisoformat(created_at_iso)
            from datetime import timedelta
            expiry = created + timedelta(days=self.retention_days)
            return datetime.now(timezone.utc) > expiry
        except (ValueError, TypeError):
            return False


# ---------------------------------------------------------------------------
# PII detection and redaction
# ---------------------------------------------------------------------------

_PII_PATTERNS: Dict[PIICategory, re.Pattern[str]] = {
    PIICategory.EMAIL: re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    PIICategory.PHONE: re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
    PIICategory.SSN: re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    PIICategory.CREDIT_CARD: re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13})\b"),
    PIICategory.IP_ADDRESS: re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
}


def detect_pii(text: str) -> Dict[PIICategory, List[str]]:
    results: Dict[PIICategory, List[str]] = {}
    for category, pattern in _PII_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            results[category] = matches
    return results


def redact_pii(text: str, categories: Optional[List[PIICategory]] = None,
               replacement: str = "[REDACTED]") -> str:
    targets = categories or list(_PII_PATTERNS.keys())
    for cat in targets:
        pattern = _PII_PATTERNS.get(cat)
        if pattern:
            text = pattern.sub(replacement, text)
    return text


def pseudonymize(value: str, salt: str = "mrmoney") -> str:
    h = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]
    return f"pseudo_{h}"


# ---------------------------------------------------------------------------
# Compliance checker
# ---------------------------------------------------------------------------

class ComplianceEngine:
    def __init__(self) -> None:
        self._consents: Dict[str, ConsentRecord] = {}
        self._dpia: Dict[str, DPIA] = {}
        self._policies: List[DataRetentionPolicy] = []

    def record_consent(self, user_id: str, purpose: str,
                       legal_basis: LegalBasis = LegalBasis.CONSENT,
                       expires_at: Optional[str] = None) -> ConsentRecord:
        rec = ConsentRecord(
            user_id=user_id,
            purpose=purpose,
            legal_basis=legal_basis,
            granted=True,
            expires_at=expires_at,
        )
        self._consents[rec.id] = rec
        return rec

    def revoke_consent(self, consent_id: str) -> bool:
        rec = self._consents.get(consent_id)
        if not rec:
            return False
        rec.revoke()
        return True

    def has_active_consent(self, user_id: str, purpose: str) -> bool:
        for rec in self._consents.values():
            if rec.user_id == user_id and rec.purpose == purpose and rec.is_active:
                return True
        return False

    def create_dpia(self, title: str, description: str,
                    data_categories: List[str]) -> DPIA:
        dpia = DPIA(title=title, description=description,
                     data_categories=data_categories)
        self._dpia[dpia.id] = dpia
        return dpia

    def get_dpia(self, dpia_id: str) -> Optional[DPIA]:
        return self._dpia.get(dpia_id)

    def add_retention_policy(self, data_category: str, retention_days: int,
                             auto_delete: bool = False) -> DataRetentionPolicy:
        policy = DataRetentionPolicy(
            data_category=data_category,
            retention_days=retention_days,
            auto_delete=auto_delete,
        )
        self._policies.append(policy)
        return policy

    def check_document_compliance(self, text: str,
                                  consented_categories: Optional[List[str]] = None,
                                  ) -> Dict[str, Any]:
        pii = detect_pii(text)
        issues: List[Dict[str, str]] = []
        for cat, matches in pii.items():
            issues.append({
                "type": "pii_detected",
                "category": cat.value,
                "count": len(matches),
                "severity": "high",
                "recommendation": f"Redact {cat.value} before storage or sharing",
            })
        consented = set(consented_categories or [])
        for cat in pii:
            if cat.value not in consented:
                issues.append({
                    "type": "missing_consent",
                    "category": cat.value,
                    "severity": "medium",
                    "recommendation": f"Obtain consent for processing {cat.value} data",
                })
        return {
            "compliant": len(issues) == 0,
            "pii_detected": {k.value: v for k, v in pii.items()},
            "issues": issues,
            "total_issues": len(issues),
        }
