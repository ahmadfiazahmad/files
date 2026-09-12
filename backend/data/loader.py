"""
Loads static reference datasets (HEC list, banned agents) into memory once.
These are reference data, not user data - a JSON file is genuinely fine even
in production since it updates rarely.
"""
import json
from pathlib import Path
from difflib import SequenceMatcher

DATA_DIR = Path(__file__).parent


def _load_json(filename: str) -> dict:
    with open(DATA_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


_hec_data = _load_json("hec_recognized.json")
_banned_agents_data = _load_json("banned_agents.json")


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def lookup_hec_institution(name: str, threshold: float = 0.75) -> dict | None:
    """Fuzzy-match university name against the static HEC list."""
    best_match, best_score = None, 0.0
    for inst in _hec_data["institutions"]:
        score = _similar(name, inst["name"])
        if score > best_score:
            best_match, best_score = inst, score

    if best_match and best_score >= threshold:
        return {**best_match, "match_confidence": round(best_score, 2)}
    return None


def lookup_banned_agent(name: str, threshold: float = 0.75) -> dict | None:
    """Fuzzy-match agent name against the static banned/warned agents list."""
    best_match, best_score = None, 0.0
    for agent in _banned_agents_data["agents"]:
        score = _similar(name, agent["agent_name"])
        if score > best_score:
            best_match, best_score = agent, score

    if best_match and best_score >= threshold:
        return {**best_match, "match_confidence": round(best_score, 2)}
    return None
