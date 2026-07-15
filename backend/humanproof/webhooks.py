"""Webhook delivery system for Mr Money AI."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from .models import utc_now


EVENT_TYPES = [
    "review.completed",
    "document.uploaded",
    "comment.added",
    "workflow.completed",
    "batch.completed",
]


@dataclass
class WebhookSubscription:
    id: str
    org_id: str
    url: str
    event_types: List[str]
    signing_secret: str
    enabled: bool = True
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "orgId": self.org_id,
            "url": self.url,
            "eventTypes": self.event_types,
            "enabled": self.enabled,
            "createdAt": self.created_at,
        }


@dataclass
class WebhookDelivery:
    id: str
    webhook_id: str
    event_type: str
    payload: Dict[str, Any]
    status: str = "pending"
    status_code: Optional[int] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    delivered_at: Optional[str] = None
    attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "webhookId": self.webhook_id,
            "eventType": self.event_type,
            "status": self.status,
            "statusCode": self.status_code,
            "attempts": self.attempts,
            "createdAt": self.created_at,
            "deliveredAt": self.delivered_at,
        }


class WebhookManager:
    def __init__(self) -> None:
        self._subscriptions: Dict[str, WebhookSubscription] = {}
        self._deliveries: Deque[WebhookDelivery] = deque(maxlen=1000)
        self._delivery_queue: Deque[WebhookDelivery] = deque()
        self._lock = threading.Lock()
        self._running = False
        self._worker: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._worker = threading.Thread(target=self._delivery_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._running = False

    def create_subscription(
        self,
        org_id: str,
        url: str,
        event_types: List[str],
    ) -> WebhookSubscription:
        sub_id = str(secrets.token_hex(16))
        signing_secret = secrets.token_hex(32)
        sub = WebhookSubscription(
            id=sub_id,
            org_id=org_id,
            url=url,
            event_types=event_types,
            signing_secret=signing_secret,
        )
        self._subscriptions[sub_id] = sub
        return sub

    def remove_subscription(self, sub_id: str) -> bool:
        return self._subscriptions.pop(sub_id, None) is not None

    def list_subscriptions(self, org_id: str) -> List[WebhookSubscription]:
        return [s for s in self._subscriptions.values() if s.org_id == org_id]

    def emit_event(self, org_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        subscriptions = [s for s in self._subscriptions.values() if s.org_id == org_id and s.enabled and event_type in s.event_types]
        for sub in subscriptions:
            delivery = WebhookDelivery(
                id=str(secrets.token_hex(16)),
                webhook_id=sub.id,
                event_type=event_type,
                payload=payload,
            )
            with self._lock:
                self._delivery_queue.append(delivery)
                self._deliveries.append(delivery)

    def get_delivery_status(self, delivery_id: str) -> Optional[WebhookDelivery]:
        for delivery in self._deliveries:
            if delivery.id == delivery_id:
                return delivery
        return None

    def get_delivery_stats(self, org_id: str) -> Dict[str, Any]:
        org_deliveries = [d for d in self._deliveries if any(
            s.org_id == org_id for s in self._subscriptions.values() if s.id == d.webhook_id
        )]
        total = len(org_deliveries)
        delivered = sum(1 for d in org_deliveries if d.status == "delivered")
        failed = sum(1 for d in org_deliveries if d.status == "failed")
        pending = sum(1 for d in org_deliveries if d.status == "pending")
        return {
            "total": total,
            "delivered": delivered,
            "failed": failed,
            "pending": pending,
            "success_rate": round(delivered / total, 3) if total > 0 else 0.0,
        }

    def _delivery_loop(self) -> None:
        while self._running:
            deliveries = []
            with self._lock:
                while self._delivery_queue:
                    deliveries.append(self._delivery_queue.popleft())
            for delivery in deliveries:
                self._deliver(delivery)
            time.sleep(1)

    def _deliver(self, delivery: WebhookDelivery) -> None:
        sub = self._subscriptions.get(delivery.webhook_id)
        if not sub:
            delivery.status = "failed"
            delivery.error = "Subscription not found"
            return

        delivery.attempts += 1
        body = json.dumps({
            "event": delivery.event_type,
            "data": delivery.payload,
            "deliveryId": delivery.id,
            "timestamp": delivery.created_at,
            "attempt": delivery.attempts,
        }, default=str).encode("utf-8")

        signature = hmac.new(sub.signing_secret.encode(), body, hashlib.sha256).hexdigest()

        try:
            req = Request(
                sub.url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": f"sha256={signature}",
                    "X-Webhook-Event": delivery.event_type,
                    "User-Agent": "MrMoneyAI-Webhook/0.3",
                },
                method="POST",
            )
            with urlopen(req, timeout=10) as resp:
                delivery.status_code = resp.status
                delivery.status = "delivered"
                delivery.delivered_at = utc_now()
        except URLError as exc:
            delivery.status_code = getattr(exc, "code", 0)
            delivery.error = str(exc)
            self._schedule_retry(delivery)
        except Exception as exc:
            delivery.error = str(exc)
            self._schedule_retry(delivery)

    def _schedule_retry(self, delivery: WebhookDelivery) -> None:
        max_attempts = 5
        if delivery.attempts < max_attempts:
            delay = min(2 ** delivery.attempts, 300)
            threading.Timer(delay, self._requeue, args=[delivery]).start()
        else:
            delivery.status = "failed"

    def _requeue(self, delivery: WebhookDelivery) -> None:
        with self._lock:
            self._delivery_queue.append(delivery)
