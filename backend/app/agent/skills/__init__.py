"""Load application Agent skills from the standard ``<name>/SKILL.md`` layout."""

from functools import lru_cache
from pathlib import Path
import re


_SKILLS_ROOT = Path(__file__).resolve().parent
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@lru_cache(maxsize=None)
def load_skill(name: str) -> str:
    """Return a skill's instruction body after validating its entrypoint metadata."""
    if not _SKILL_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid skill name: {name!r}")

    skill_file = _SKILLS_ROOT / name / "SKILL.md"
    try:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ValueError(f"Skill not found: {name}") from exc

    if not lines or lines[0] != "---":
        raise ValueError(f"Skill {name!r} is missing YAML frontmatter")
    try:
        frontmatter_end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"Skill {name!r} has unterminated YAML frontmatter") from exc

    metadata = {}
    for line in lines[1:frontmatter_end]:
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip()

    if metadata.get("name") != name:
        raise ValueError(f"Skill {name!r} frontmatter name must match its directory")
    if not metadata.get("description"):
        raise ValueError(f"Skill {name!r} must declare a description")

    body = "\n".join(lines[frontmatter_end + 1:]).strip()
    if not body:
        raise ValueError(f"Skill {name!r} has no instructions")
    return body
