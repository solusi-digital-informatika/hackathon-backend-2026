"""
Simple heuristic extractor for creative brief text.

This is a deterministic first-pass extraction:
- It splits the text into labelled sections by scanning for known keywords.
- It does NOT call an LLM; AI extraction can be layered on top later.

Rationale: the brief text has a semi-structured format. A deterministic
extractor is testable, predictable, and sufficient for M2. An LLM can replace
or augment this when the project reaches the inference milestone.
"""

import re


def _find_section(text: str, *keywords: str) -> str:
    """
    Return the value of the first labelled line whose label matches any keyword.
    Format expected: "Label: value" anywhere in the text.
    Returns empty string when not found.
    """
    for keyword in keywords:
        pattern = re.compile(
            rf"(?:^|\n)\s*{re.escape(keyword)}\s*[:\-]\s*(.+?)(?=\n\s*\w|$)",
            re.IGNORECASE | re.DOTALL,
        )
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
    return ""


def _extract_list_section(text: str, *keywords: str) -> list[str]:
    """
    Return lines under a section heading as a list of non-blank strings.
    Handles bullet/dash prefixes.
    """
    for keyword in keywords:
        pattern = re.compile(
            rf"(?:^|\n)\s*{re.escape(keyword)}\s*[:\-]\s*\n((?:\s*[-*•]?\s*.+\n?)+)",
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if m:
            lines = m.group(1).splitlines()
            items = []
            for line in lines:
                cleaned = re.sub(r"^[\s\-*•]+", "", line).strip()
                if cleaned:
                    items.append(cleaned)
            return items
    return []


def extract(content: str) -> dict:
    """
    Parse raw brief text and return a dict matching ProjectBrief fields.
    All fields fall back to empty strings / empty lists when absent.
    """
    objective = _find_section(content, "Objective", "Summary", "Overview", "Goal")
    visual_style = _find_section(
        content, "Art Style", "Visual Style", "Style", "Aesthetic"
    )
    lighting_mood = _find_section(
        content, "Lighting", "Lighting & Color", "Lighting and Color", "Mood", "Color Palette"
    )

    characters_raw = _extract_list_section(content, "Characters", "Character", "Cast")
    characters = []
    for item in characters_raw:
        # Format: "Name: details" or just plain text
        if ":" in item:
            parts = item.split(":", 1)
            characters.append({"name": parts[0].strip(), "details": parts[1].strip()})
        else:
            characters.append({"name": item, "details": ""})

    props_raw = _extract_list_section(content, "Key Props", "Props", "Key Objects", "Artifacts")
    key_props = []
    for item in props_raw:
        if ":" in item:
            parts = item.split(":", 1)
            key_props.append({"name": parts[0].strip(), "details": parts[1].strip()})
        else:
            key_props.append({"name": item, "details": ""})

    constraints = _extract_list_section(
        content, "Constraints", "Requirements", "Rules", "Restrictions"
    )
    unresolved = _extract_list_section(
        content,
        "Unresolved Questions",
        "Open Questions",
        "Questions",
        "Unknowns",
        "Clarifications",
    )

    return {
        "objective": objective,
        "visual_style": visual_style,
        "lighting_mood": lighting_mood,
        "characters": characters,
        "key_props": key_props,
        "constraints": constraints,
        "unresolved_questions": unresolved,
    }
