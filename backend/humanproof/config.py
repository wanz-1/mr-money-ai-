"""Environment configuration loader for Mr Money AI.

Loads .env file from project root. Does not override existing env vars.
Supports variable interpolation (${VAR} syntax) and required key validation.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("humanproof.config")

_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def load_env(env_path: str | Path | None = None, required_keys: list[str] | None = None) -> None:
    if env_path is None:
        env_path = Path(__file__).resolve().parents[2] / ".env"
    else:
        env_path = Path(env_path)

    if not env_path.exists():
        logger.debug("No .env file found at %s", env_path)
        return

    with open(env_path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    parsed: dict[str, str] = {}
    for line in raw_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if key:
            parsed[key] = value

    def _interpolate(val: str) -> str:
        def _replace(m: re.Match) -> str:
            ref_key = m.group(1)
            return parsed.get(ref_key, os.environ.get(ref_key, m.group(0)))
        return _VAR_PATTERN.sub(_replace, val)

    for key, value in parsed.items():
        interpolated = _interpolate(value)
        if key not in os.environ:
            os.environ[key] = interpolated

    if required_keys:
        missing = [k for k in required_keys if k not in os.environ and k not in parsed]
        if missing:
            logger.warning("Missing required environment variables: %s", ", ".join(missing))
