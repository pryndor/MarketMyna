"""Strategy/skill library: loads marketmyna/strategies/*.yaml into Skill objects and
selects a handful relevant to a given market regime or query.

See marketmyna/strategies/README.md for what these files are and how required_tools
was adapted from daily_stock_analysis's own strategy library.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# marketmyna/agent/skills.py -> project root is two levels up.
_DEFAULT_STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"


@dataclass
class Skill:
    name: str
    display_name: str
    description: str = ""
    category: str = ""
    core_rules: list = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    default_priority: int = 0
    market_regimes: list[str] = field(default_factory=list)
    instructions: str = ""
    default_active: bool = False
    default_router: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            description=data.get("description", ""),
            category=data.get("category", ""),
            core_rules=data.get("core_rules", []) or [],
            required_tools=data.get("required_tools", []) or [],
            aliases=data.get("aliases", []) or [],
            default_priority=data.get("default_priority", 0),
            market_regimes=data.get("market_regimes", []) or [],
            instructions=data.get("instructions", ""),
            default_active=bool(data.get("default_active", False)),
            default_router=bool(data.get("default_router", False)),
        )


class SkillManager:
    """Loads the builtin skill library and answers "which skills apply
    here" queries. Deliberately simple matching (substring/membership,
    sort by priority) - no embeddings or fuzzy scoring, that would be
    over-engineering for a first cut of this feature."""

    def __init__(self, strategies_dir: Optional[Path] = None):
        self.strategies_dir = Path(strategies_dir) if strategies_dir else _DEFAULT_STRATEGIES_DIR
        self._skills: list[Skill] = []

    def load_builtin_skills(self, strategies_dir: Optional[Path] = None) -> list[Skill]:
        directory = Path(strategies_dir) if strategies_dir else self.strategies_dir
        skills: list[Skill] = []

        if not directory.exists():
            logger.warning("Strategies directory does not exist: %s", directory)
            self._skills = skills
            return skills

        for path in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "name" not in data:
                    raise ValueError("missing required 'name' field")
                skills.append(Skill.from_dict(data))
            except Exception as exc:
                logger.warning("Skipping malformed strategy file %s: %s", path, exc)
                continue

        self._skills = skills
        return skills

    @property
    def skills(self) -> list[Skill]:
        return self._skills

    def select_skills(
        self,
        market_regime: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 3,
    ) -> list[Skill]:
        candidates = self._skills

        if market_regime:
            regime_matches = [s for s in candidates if market_regime in s.market_regimes]
            # Only narrow to regime-matching skills if any actually match -
            # an unmatched regime falls back to the full (query-filtered)
            # set rather than returning nothing.
            if regime_matches:
                candidates = regime_matches

        if query:
            q = query.strip().lower()
            candidates = [
                s
                for s in candidates
                if q in s.name.lower()
                or q in s.display_name.lower()
                or any(q in alias.lower() for alias in s.aliases)
            ]

        ranked = sorted(candidates, key=lambda s: s.default_priority, reverse=True)
        return ranked[:limit]
