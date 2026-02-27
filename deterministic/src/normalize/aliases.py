"""Field alias resolution: map raw labels to canonical field names.

Loads config/field_aliases.json and provides fast lookup.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class AliasResolver:
    """Resolves raw field labels to canonical names using aliases config."""

    def __init__(self, config_path: str = ""):
        self._aliases: Dict[str, List[str]] = {}
        self._multipliers: Dict[str, Optional[float]] = {}
        self._lookup: Dict[str, str] = {}  # normalized alias -> canonical

        if not config_path:
            config_path = str(
                Path(__file__).parent.parent.parent / "config" / "field_aliases.json"
            )

        self._load(config_path)

    def _load(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.exists():
            return

        data = json.loads(path.read_text(encoding="utf-8"))
        for canonical, config in data.items():
            if canonical.startswith("_"):
                continue
            aliases = config.get("aliases", [])
            multiplier = config.get("multiplier")
            self._aliases[canonical] = aliases
            self._multipliers[canonical] = multiplier

            # Build lookup: normalized alias -> canonical
            self._lookup[self._normalize(canonical)] = canonical
            for alias in aliases:
                self._lookup[self._normalize(alias)] = canonical

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize a label for matching."""
        text = text.lower().strip()
        # Remove common punctuation
        text = re.sub(r"['''\",():]", "", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def resolve(self, raw_label: str) -> Optional[str]:
        """Resolve a raw label to its canonical field name.

        Returns None if no match found.
        """
        normalized = self._normalize(raw_label)
        if normalized in self._lookup:
            return self._lookup[normalized]

        # Fuzzy: try substring match (label contains an alias)
        for alias_norm, canonical in self._lookup.items():
            if len(alias_norm) >= 4 and alias_norm in normalized:
                return canonical

        return None

    def get_multiplier(self, canonical_name: str) -> Optional[float]:
        """Get the scale multiplier for a canonical field. None = no assumption."""
        return self._multipliers.get(canonical_name)

    def get_all_canonical_names(self) -> List[str]:
        """Return all known canonical field names."""
        return list(self._aliases.keys())
