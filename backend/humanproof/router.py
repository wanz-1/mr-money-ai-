"""Intelligent multi-provider model routing for Mr Money AI.

Automatically selects the best AI model provider for each task type based on
provider availability, capabilities, and cost considerations.

Environment variables:
  HP_AI_ROUTING - "auto" | "manual" (default: auto)
"""

from __future__ import annotations

from .config import load_env
load_env()

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .ai_assistant import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    CUSTOM_API_BASE,
    CUSTOM_API_KEY,
    CUSTOM_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


ROUTING_MODE = _env("HP_AI_ROUTING", "auto")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ProviderCapability:
    name: str
    configured: bool
    model: str
    strengths: List[str] = field(default_factory=list)
    cost_tier: str = "standard"  # "low" | "standard" | "high"


@dataclass
class RoutingDecision:
    task_type: str
    provider: str
    model: str
    reason: str
    alternatives: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Task type definitions
# ---------------------------------------------------------------------------

TASK_TYPES = ("chat", "code", "analysis", "creative", "research", "summarize", "translate")

# Ordered preference lists per task type.
# Each entry is (provider_key, reason).
TASK_PREFERENCES: Dict[str, List[tuple[str, str]]] = {
    "code": [
        ("openai", "GPT-4o strong at code generation and debugging"),
        ("anthropic", "Claude excels at code review and explanation"),
        ("custom", "Custom model with domain-specific code training"),
        ("local", "Local fallback using built-in review agents"),
    ],
    "analysis": [
        ("anthropic", "Claude strong at nuanced analysis and reasoning"),
        ("openai", "GPT-4o capable at structured analysis tasks"),
        ("custom", "Custom model with domain-specific analysis"),
        ("local", "Local fallback with built-in analyzers"),
    ],
    "creative": [
        ("anthropic", "Claude excels at creative writing and brainstorming"),
        ("openai", "GPT-4o capable at creative tasks"),
        ("custom", "Custom model with creative fine-tuning"),
    ],
    "research": [
        ("openai", "GPT-4o with broad knowledge and web search context"),
        ("custom", "Custom model with research-augmented context"),
        ("anthropic", "Claude capable at research synthesis"),
    ],
    "summarize": [
        ("custom", "Custom model optimized for cost-efficient summarization"),
        ("openai", "GPT-4o for complex summaries"),
        ("anthropic", "Claude for detailed summaries"),
    ],
    "translate": [
        ("custom", "Custom model optimized for translation"),
        ("openai", "GPT-4o multilingual capability"),
        ("anthropic", "Claude multilingual capability"),
    ],
    "chat": [
        ("openai", "GPT-4o general-purpose conversation"),
        ("anthropic", "Claude conversational AI"),
        ("custom", "Custom conversational model"),
        ("local", "Local assistant with built-in knowledge"),
    ],
}


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

def _build_providers() -> Dict[str, ProviderCapability]:
    """Build the registry of available providers based on env config."""
    providers: Dict[str, ProviderCapability] = {}

    providers["openai"] = ProviderCapability(
        name="OpenAI",
        configured=bool(OPENAI_API_KEY),
        model=OPENAI_MODEL,
        strengths=["code", "analysis", "research", "chat"],
        cost_tier="high",
    )

    providers["anthropic"] = ProviderCapability(
        name="Anthropic",
        configured=bool(ANTHROPIC_API_KEY),
        model=ANTHROPIC_MODEL,
        strengths=["analysis", "creative", "code"],
        cost_tier="high",
    )

    providers["custom"] = ProviderCapability(
        name="Custom",
        configured=bool(CUSTOM_API_KEY and CUSTOM_API_BASE),
        model=CUSTOM_MODEL,
        strengths=["summarize", "translate", "code", "research"],
        cost_tier="low",
    )

    providers["local"] = ProviderCapability(
        name="Local",
        configured=True,
        model="built-in",
        strengths=["chat", "code", "analysis"],
        cost_tier="low",
    )

    return providers


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------

class ModelRouter:
    """Selects the best provider for a given task type.

    When routing mode is ``"auto"`` the router walks the preference list for
    the requested task type and returns the first provider that is configured.
    In ``"manual"`` mode it always defers to the explicitly configured
    ``HP_AI_PROVIDER`` value.
    """

    def __init__(self) -> None:
        self.providers = _build_providers()
        self.mode = ROUTING_MODE

    def route(self, task_type: str, message: str = "") -> RoutingDecision:
        """Return the best provider for *task_type*.

        Parameters
        ----------
        task_type:
            One of the supported task types (see ``TASK_TYPES``).
        message:
            Optional user message for future context-aware routing.

        Returns
        -------
        RoutingDecision
            Contains the chosen provider, model, reason, and alternatives.
        """
        if task_type not in TASK_TYPES:
            task_type = "chat"

        if self.mode == "manual":
            from .ai_assistant import _detect_provider
            manual = _detect_provider()
            return RoutingDecision(
                task_type=task_type,
                provider=manual,
                model=self.providers[manual].model,
                reason="Manual routing mode -- using HP_AI_PROVIDER",
            )

        preferences = TASK_PREFERENCES.get(task_type, TASK_PREFERENCES["chat"])
        alternatives: List[str] = []

        for provider_key, reason in preferences:
            cap = self.providers.get(provider_key)
            if cap and cap.configured:
                return RoutingDecision(
                    task_type=task_type,
                    provider=provider_key,
                    model=cap.model,
                    reason=reason,
                    alternatives=alternatives,
                )
            alternatives.append(provider_key)

        # All providers failed -- fall back to local.
        local = self.providers["local"]
        return RoutingDecision(
            task_type=task_type,
            provider="local",
            model=local.model,
            reason="No external providers configured -- using local fallback",
        )


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_router: Optional[ModelRouter] = None


def _get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def route_task(task_type: str, message: str = "") -> str:
    """Return the provider name to use for *task_type*.

    This is the primary public entry point for routing.  It returns a string
    such as ``"openai"``, ``"anthropic"``, ``"custom"``, or ``"local"``.
    """
    decision = _get_router().route(task_type, message)
    return decision.provider


def get_routing_info() -> Dict[str, Any]:
    """Return available providers and per-task-type routing decisions."""
    router = _get_router()

    provider_info: Dict[str, Dict[str, Any]] = {}
    for key, cap in router.providers.items():
        provider_info[key] = {
            "name": cap.name,
            "configured": cap.configured,
            "model": cap.model,
            "strengths": cap.strengths,
            "costTier": cap.cost_tier,
        }

    task_decisions: Dict[str, Dict[str, str]] = {}
    for task in TASK_TYPES:
        decision = router.route(task)
        task_decisions[task] = {
            "provider": decision.provider,
            "model": decision.model,
            "reason": decision.reason,
        }

    return {
        "mode": router.mode,
        "providers": provider_info,
        "taskRouting": task_decisions,
    }
