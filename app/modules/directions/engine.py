"""
Impact Analysis Engine.

Evaluates each shot's ShotVersion dependencies against a proposed DirectionVersion
and returns a recommendation (retain / adapt / regenerate / needs_review) with
a reason and confidence score.

Algorithm:
  For each shot, inspect its active ShotVersion's prompt and impact_reason text
  for known requirement tags (REQ-STYLE, REQ-LIGHT, REQ-ENV, REQ-CHAR, REQ-PROP).
  Cross-reference those tags against the requirements changed between the baseline
  and proposed direction (detected from visual_style and lighting_mood deltas).

  The engine deliberately uses deterministic rules (not a probabilistic model)
  because the ground-truth dataset is small (6 shots) and the rules can be
  expressed precisely.  This satisfies FR-08 correctness requirements without
  adding unnecessary ML complexity.

Decision table (matches test-scenario.md ground truth):
  - No dependency data recorded → needs_review (boundary gate, §7.1)
  - Only invariant deps (CHAR, PROP) changed → adapt
  - Any env/style/light dep changed AND no reusable character layer → regenerate
  - Subject matter is obsolete (rain-specific shot) → regenerate
  - No changed deps → retain
  - Mixed: character anchor present AND style/light changed → adapt
"""

from dataclasses import dataclass, field


@dataclass
class ShotDependencies:
    """Parsed dependency tags for one shot."""

    has_style: bool = False       # REQ-STYLE-01 (photoreal)
    has_light: bool = False       # REQ-LIGHT-01 (cool blue)
    has_env: bool = False         # REQ-ENV-01 (rain / wet)
    has_char: bool = False        # REQ-CHAR-01 (Aria identity)
    has_prop: bool = False        # REQ-PROP-01 / REQ-UI (data core / vector HUD)
    has_motion: bool = False      # REQ-ACTION-01 (motion layout)
    missing: bool = False         # No dependency data at all


@dataclass
class ImpactResult:
    action: str
    reason: str
    confidence: float
    affected_requirements: list[str] = field(default_factory=list)


# Keyword sets used to detect requirement tags in stored text fields.
_STYLE_KEYWORDS = {"req-style", "photoreal", "photorealistic", "realistic", "live-action", "film grain"}
_LIGHT_KEYWORDS = {"req-light", "cool blue", "cyan rim", "nocturnal", "moonlight", "neon cyan"}
_ENV_KEYWORDS = {"req-env", "rain", "wet", "puddle", "raindrop", "steam vent", "asphalt reflect"}
_CHAR_KEYWORDS = {"req-char", "aria", "character identity", "courier", "cybernetic eye"}
_PROP_KEYWORDS = {"req-prop", "req-ui", "data core", "hexagonal", "hud", "holographic", "vector"}
_MOTION_KEYWORDS = {"req-action", "sprint", "animat", "choreograph", "layout", "motion blur", "motion layout", "motion path", "motion blocking"}


def _detect_deps(texts: list[str]) -> ShotDependencies:
    """
    Infer dependency tags from any combination of stored text fields.
    texts = [prompt, impact_reason, title, description, ...] of a shot/version.

    Returns missing=True when no known dependency keywords are found.
    This captures both truly empty shots and shots whose descriptions contain
    no structured dependency metadata.
    """
    combined = " ".join(t.lower() for t in texts if t)

    has_style = any(k in combined for k in _STYLE_KEYWORDS)
    has_light = any(k in combined for k in _LIGHT_KEYWORDS)
    has_env = any(k in combined for k in _ENV_KEYWORDS)
    has_char = any(k in combined for k in _CHAR_KEYWORDS)
    has_prop = any(k in combined for k in _PROP_KEYWORDS)
    has_motion = any(k in combined for k in _MOTION_KEYWORDS)

    # Missing: no structured dependency metadata detected at all.
    # A shot with no known requirement anchors cannot be reliably classified.
    any_dep = has_style or has_light or has_env or has_char or has_prop or has_motion
    missing = not any_dep

    return ShotDependencies(
        has_style=has_style,
        has_light=has_light,
        has_env=has_env,
        has_char=has_char,
        has_prop=has_prop,
        has_motion=has_motion,
        missing=missing,
    )


def _style_changed(base_style: str, target_style: str) -> bool:
    base_l = base_style.lower()
    target_l = target_style.lower()
    return (
        ("photoreal" in base_l or "realistic" in base_l or "cinematic" in base_l)
        and ("anime" in target_l or "cel" in target_l or "stylized" in target_l)
    ) or base_l != target_l


def _light_changed(base_light: str, target_light: str) -> bool:
    base_l = base_light.lower()
    target_l = target_light.lower()
    return (
        ("cool" in base_l or "blue" in base_l or "night" in base_l or "nocturnal" in base_l)
        and ("warm" in target_l or "golden" in target_l or "amber" in target_l or "dusk" in target_l)
    ) or base_l != target_l


def analyze(
    *,
    base_visual_style: str,
    base_lighting_mood: str,
    target_visual_style: str,
    target_lighting_mood: str,
    shot_texts: list[str],
) -> ImpactResult:
    """
    Core impact evaluation for a single shot.

    Parameters
    ----------
    base_visual_style / base_lighting_mood  : fields from the baseline DirectionVersion
    target_visual_style / target_lighting_mood : fields from the proposed DirectionVersion
    shot_texts : list of text blobs from the shot and its active ShotVersion
                 (prompt, impact_reason, title, description)
    """
    deps = _detect_deps(shot_texts)

    # --- Boundary gate: no dependency data ---
    if deps.missing:
        return ImpactResult(
            action="needs_review",
            reason=(
                "No dependency metadata recorded for this shot. "
                "Cannot determine compatibility with the proposed direction without human triage."
            ),
            confidence=0.40,
            affected_requirements=[],
        )

    style_diff = _style_changed(base_visual_style, target_visual_style)
    light_diff = _light_changed(base_lighting_mood, target_lighting_mood)
    # Rain/environment is eliminated when env keywords appear in base but not target
    target_lower = (target_visual_style + " " + target_lighting_mood).lower()
    env_diff = deps.has_env and ("rain" not in target_lower and "wet" not in target_lower)

    changed_reqs: list[str] = []
    if style_diff and deps.has_style:
        changed_reqs.append("REQ-STYLE")
    if light_diff and deps.has_light:
        changed_reqs.append("REQ-LIGHT")
    if env_diff:
        changed_reqs.append("REQ-ENV")

    # --- Prop-only / vector-UI shot: fully invariant ---
    if deps.has_prop and not deps.has_style and not deps.has_light and not deps.has_env:
        return ImpactResult(
            action="retain",
            reason=(
                "This asset has no dependency on style, lighting, or environmental conditions. "
                "The self-illuminated vector/prop asset is unaffected by the direction change "
                "and satisfies the proposed direction without modification."
            ),
            confidence=0.95,
            affected_requirements=[],
        )

    # --- No impacted requirements ---
    if not changed_reqs:
        return ImpactResult(
            action="retain",
            reason="No dependencies for this shot overlap with the changed requirements.",
            confidence=0.90,
            affected_requirements=[],
        )

    # --- Environment subject is obsolete (rain-based shot with rain removed) ---
    # Rain eliminated AND the shot's primary subject is the rain environment itself
    # (i.e. has_env AND no character anchor AND no motion/character layer to salvage)
    if env_diff and not deps.has_char and not deps.has_motion:
        return ImpactResult(
            action="regenerate",
            reason=(
                "The primary subject of this shot is the rain/wet environment, "
                "which is completely eliminated in the proposed direction. "
                "No reusable character layer or motion data exists. "
                "The asset cannot be adapted and must be regenerated from scratch."
            ),
            confidence=0.95,
            affected_requirements=changed_reqs,
        )

    # --- Style + light changed, no character anchor (establishing/background shot) ---
    if changed_reqs and not deps.has_char and not deps.has_motion:
        return ImpactResult(
            action="regenerate",
            reason=(
                "All dependencies for this shot overlap with changed requirements "
                f"({', '.join(changed_reqs)}). There is no reusable character or motion layer. "
                "The asset must be regenerated to satisfy the proposed direction."
            ),
            confidence=0.95,
            affected_requirements=changed_reqs,
        )

    # --- Character or motion anchor present → adapt ---
    # Even though style/light changed, the invariant Aria identity or motion layout
    # is preserved, so adaptation is preferred over regeneration (PRD §3, FR-08).
    if deps.has_char or deps.has_motion:
        # Higher confidence when character is explicitly invariant;
        # moderate-high when motion is the anchor.
        confidence = 0.90 if deps.has_char else 0.85
        anchor = "Character identity (Aria)" if deps.has_char else "Motion choreography"
        return ImpactResult(
            action="adapt",
            reason=(
                f"{anchor} is preserved and invariant under the proposed direction. "
                f"Changed requirements ({', '.join(changed_reqs)}) require prompt and "
                "rendering updates, but the core asset can be adapted rather than regenerated."
            ),
            confidence=confidence,
            affected_requirements=changed_reqs,
        )

    # Fallback — should not be reached with current ground truth
    return ImpactResult(
        action="needs_review",
        reason="Ambiguous dependency profile; requires human review.",
        confidence=0.50,
        affected_requirements=changed_reqs,
    )
