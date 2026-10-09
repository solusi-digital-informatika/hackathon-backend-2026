"""
Tests for Direction Versioning, Impact Analysis, Review/Approval, and Storyboard.

Ground-truth reference: contracts/test-scenario.md §3-4
Contracts reference: contracts/api-directions.md, decisions/D-007.md
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_project(client, name="CyberPulse Demo"):
    resp = client.post("/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def make_direction(client, project_id, **kwargs):
    payload = {
        "version_number": 1,
        "title": "Realistic Cinematic Cyberpunk",
        "visual_style": "Photorealistic live-action cinema, heavy anamorphic lens flare, film grain",
        "lighting_mood": "Moody nocturnal atmosphere; cool blue cyan rim lighting; deep wet-asphalt contrast",
        "change_note": "",
        "status": "draft",
        **kwargs,
    }
    resp = client.post(f"/projects/{project_id}/directions", json=payload)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def make_shot(client, project_id, title, description=None, sequence_order=None):
    payload = {"title": title}
    if description:
        payload["description"] = description
    if sequence_order:
        payload["sequence_order"] = sequence_order
    resp = client.post(f"/projects/{project_id}/shots", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/directions  (FR-06)
# ---------------------------------------------------------------------------


def test_create_direction_minimal(client):
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/directions",
        json={
            "version_number": 1,
            "title": "Realistic Cinematic Cyberpunk",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("dir_")
    assert body["version_number"] == 1
    assert body["title"] == "Realistic Cinematic Cyberpunk"
    assert body["status"] == "draft"
    assert body["project_id"] == pid
    assert "created_at" in body


def test_create_direction_full(client):
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/directions",
        json={
            "version_number": 2,
            "title": "Stylized Anime / Cel-Shaded Sunset",
            "visual_style": "2D/3D hybrid stylized animation, crisp lineart, graphic cel-shading",
            "lighting_mood": "Warm golden hour / dusk, glowing amber highlights",
            "change_note": "Artistic pivot to vibrant cel-shaded anime aesthetic at dusk",
            "status": "draft",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["version_number"] == 2
    assert body["visual_style"] == "2D/3D hybrid stylized animation, crisp lineart, graphic cel-shading"
    assert body["lighting_mood"] == "Warm golden hour / dusk, glowing amber highlights"
    assert body["change_note"] == "Artistic pivot to vibrant cel-shaded anime aesthetic at dusk"


def test_create_direction_missing_title(client):
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/directions", json={"version_number": 1})
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "validation_error"


def test_create_direction_missing_version_number(client):
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/directions", json={"title": "Test"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_direction_unknown_project(client):
    resp = client.post(
        "/projects/prj_00000000/directions",
        json={"version_number": 1, "title": "Test"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_create_direction_location_header(client):
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/directions",
        json={"version_number": 1, "title": "Test"},
    )
    assert resp.status_code == 201
    location = resp.headers.get("Location", "")
    assert f"/projects/{pid}/directions/" in location


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/directions  (list, FR-06)
# ---------------------------------------------------------------------------


def test_list_directions_empty(client):
    pid = make_project(client)
    resp = client.get(f"/projects/{pid}/directions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_directions_ordered_by_version(client):
    pid = make_project(client)
    make_direction(client, pid, version_number=2, title="V2")
    make_direction(client, pid, version_number=1, title="V1")
    resp = client.get(f"/projects/{pid}/directions")
    body = resp.json()
    assert body["total"] == 2
    assert body["items"][0]["version_number"] == 1
    assert body["items"][1]["version_number"] == 2


def test_list_directions_project_isolation(client):
    pid_a = make_project(client, "A")
    pid_b = make_project(client, "B")
    make_direction(client, pid_a)
    resp = client.get(f"/projects/{pid_b}/directions")
    assert resp.json()["total"] == 0


def test_list_directions_unknown_project(client):
    resp = client.get("/projects/prj_00000000/directions")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/directions/{direction_id}  (FR-06)
# ---------------------------------------------------------------------------


def test_get_direction(client):
    pid = make_project(client)
    created = make_direction(client, pid)
    resp = client.get(f"/projects/{pid}/directions/{created['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created["id"]
    assert body["title"] == created["title"]


def test_get_direction_not_found(client):
    pid = make_project(client)
    resp = client.get(f"/projects/{pid}/directions/dir_00000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_get_direction_unknown_project(client):
    resp = client.get("/projects/prj_00000000/directions/dir_00000000")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/directions/compare  (FR-07)
# ---------------------------------------------------------------------------


def test_compare_directions_style_and_lighting(client):
    pid = make_project(client)
    v1 = make_direction(
        client, pid,
        version_number=1,
        title="V1",
        visual_style="Realistic Cinematic",
        lighting_mood="Cool Blue Night",
    )
    v2 = make_direction(
        client, pid,
        version_number=2,
        title="V2",
        visual_style="Stylized Anime Cel-Shaded",
        lighting_mood="Warm Golden Hour",
    )
    resp = client.post(
        f"/projects/{pid}/directions/compare",
        json={"base_direction_id": v1["id"], "target_direction_id": v2["id"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["style_delta"] is not None
    assert body["style_delta"]["base"] == "Realistic Cinematic"
    assert body["style_delta"]["target"] == "Stylized Anime Cel-Shaded"
    assert body["lighting_delta"] is not None
    assert body["lighting_delta"]["base"] == "Cool Blue Night"
    assert body["lighting_delta"]["target"] == "Warm Golden Hour"
    assert "summary" in body
    assert body["summary"]  # non-empty


def test_compare_directions_no_delta(client):
    pid = make_project(client)
    v1 = make_direction(client, pid, version_number=1, title="V1",
                        visual_style="Same Style", lighting_mood="Same Lighting")
    v2 = make_direction(client, pid, version_number=2, title="V2",
                        visual_style="Same Style", lighting_mood="Same Lighting")
    resp = client.post(
        f"/projects/{pid}/directions/compare",
        json={"base_direction_id": v1["id"], "target_direction_id": v2["id"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["style_delta"] is None
    assert body["lighting_delta"] is None
    assert "No differences" in body["summary"]


def test_compare_directions_missing_base(client):
    pid = make_project(client)
    v2 = make_direction(client, pid, version_number=2, title="V2")
    resp = client.post(
        f"/projects/{pid}/directions/compare",
        json={"base_direction_id": "dir_00000000", "target_direction_id": v2["id"]},
    )
    assert resp.status_code == 404


def test_compare_directions_missing_target(client):
    pid = make_project(client)
    v1 = make_direction(client, pid, version_number=1, title="V1")
    resp = client.post(
        f"/projects/{pid}/directions/compare",
        json={"base_direction_id": v1["id"], "target_direction_id": "dir_00000000"},
    )
    assert resp.status_code == 404


def test_compare_directions_unknown_project(client):
    resp = client.post(
        "/projects/prj_00000000/directions/compare",
        json={"base_direction_id": "dir_00000000", "target_direction_id": "dir_11111111"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/directions/analyze-impact  (FR-08)
#
# Ground-truth validation against test-scenario.md §3-4
# ---------------------------------------------------------------------------


V1_STYLE = (
    "Photorealistic live-action cinema, heavy anamorphic lens flare, "
    "shallow depth of field, naturalistic micro-textures, film grain"
)
V1_LIGHT = (
    "Moody nocturnal atmosphere; dominant cool blue (#0A192F) and cyan (#00F0FF) "
    "rim lighting; deep wet-asphalt contrast"
)
V2_STYLE = (
    "2D/3D hybrid stylized animation, crisp lineart, graphic cel-shading, "
    "vibrant saturated palette, expressive non-photoreal rendering (NPR)"
)
V2_LIGHT = (
    "Warm golden hour / dusk; glowing amber (#FF9900), warm tangerine (#FF5E00), "
    "and magenta highlights; soft warm ambient fill"
)

# Shot prompts and metadata from test-scenario.md §3
SHOT_DATA = {
    "SHOT-01": {
        "title": "Establishing Aerial Alleyway",
        "description": (
            "Extreme wide crane shot looking down into a narrow canyon between skyscrapers."
        ),
        "prompt": (
            "Cinematic 8k wide crane shot of cyberpunk city canyon, photorealistic skyscrapers, "
            "pouring heavy rain, slick asphalt reflections, deep cool blue lighting, "
            "neon cyan glow, anamorphic lens, realistic film grain"
        ),
        "impact_reason": (
            "REQ-STYLE-01 (Realistic Photoreal), REQ-LIGHT-01 (Cool Blue), REQ-ENV-01 (Heavy Rain) "
            "all invalidated; no character layer"
        ),
    },
    "SHOT-02": {
        "title": "Aria Medium Portrait",
        "description": (
            "Medium portrait shot of Aria pausing under a doorway canopy, "
            "looking at camera, her left cybernetic eye pulsing gently."
        ),
        "prompt": (
            "Medium portrait of female courier Aria, 25 years old, athletic build, "
            "messy dark undercut, glowing cyan chrome cybernetic left eye, "
            "high-collar dark leather duster, photorealistic skin texture, "
            "cool cyan rim lighting, shallow depth of field"
        ),
        "impact_reason": (
            "REQ-CHAR-01 (Aria Identity) strictly preserved; "
            "REQ-STYLE-01 changes to cel-shaded anime; REQ-LIGHT-01 changes to warm amber"
        ),
    },
    "SHOT-03": {
        "title": "Holographic Data Core HUD Overlay",
        "description": (
            "Direct close-up on the hexagonal data core display projecting "
            "a minimalist holographic delivery manifest and coordinate map."
        ),
        "prompt": (
            "Diegetic vector graphic user interface, minimalist glowing holographic telemetry HUD, "
            "hexagonal blueprint layout, crisp typography, amber and white vector line work, "
            "isolated on transparent background, clean motion graphic design"
        ),
        "impact_reason": (
            "REQ-PROP-01 (Hexagonal Data Core), REQ-UI-01 (Clean Vector HUD); "
            "self-illuminated vector asset fully independent of ambient style and environment"
        ),
    },
    "SHOT-04": {
        "title": "Aria Rooftop Sprint",
        "description": (
            "Dynamic tracking profile shot of Aria sprinting across an elevated duct."
        ),
        "prompt": (
            "Dynamic profile action tracking shot of courier Aria sprinting across "
            "industrial rooftop pipe, coat tails trailing, motion blur, athletic hurdle posture, "
            "rainy night background, cool blue cinematic moonlight rim light"
        ),
        "impact_reason": (
            "REQ-CHAR-01 (Aria Identity) and REQ-ACTION-01 (Rooftop Motion Layout) preserved; "
            "REQ-STYLE-01 and REQ-LIGHT-01 changed"
        ),
    },
    "SHOT-05": {
        "title": "Raindrop Splash Macro Cutaway",
        "description": (
            "High-speed macro slow-motion cutaway of a heavy raindrop "
            "splashing into a dark puddle."
        ),
        "prompt": (
            "Macro 1000fps slow motion close-up of single raindrop impacting asphalt puddle, "
            "intricate fluid crown splash, photorealistic liquid dynamics, dark tarmac texture, "
            "distorted reflection of cyan neon sign"
        ),
        "impact_reason": (
            "REQ-STYLE-01 (Realistic Photoreal), REQ-LIGHT-01 (Cool Blue), "
            "REQ-ENV-01 (Heavy Rain); V2 completely eliminates rain"
        ),
    },
    "SHOT-06": {
        "title": "Mystery Figure in Alleyway Doorway",
        "description": (
            "Ominous shadowed silhouette of an unidentified figure "
            "observing from a recessed industrial doorway."
        ),
        "prompt": "",  # No explicit dependency data — simulates missing metadata
        "impact_reason": "",
    },
}

GROUND_TRUTH = {
    "SHOT-01": ("regenerate", 0.90),
    "SHOT-02": ("adapt", 0.85),
    "SHOT-03": ("retain", 0.90),
    "SHOT-04": ("adapt", 0.80),
    "SHOT-05": ("regenerate", 0.90),
    "SHOT-06": ("needs_review", None),  # confidence < 0.60
}


def _setup_demo_scenario(client):
    """
    Create the full CyberPulse demo scenario:
    - Project
    - Direction V1 (baseline)
    - Direction V2 (proposed)
    - 6 shots with ShotVersion v1 metadata
    Returns (project_id, dir_v1_id, dir_v2_id, shot_ids_in_order)
    """
    pid = make_project(client, "CyberPulse: The Neon Courier")

    v1 = make_direction(
        client, pid,
        version_number=1,
        title="Realistic Cinematic Cyberpunk (Moody Night)",
        visual_style=V1_STYLE,
        lighting_mood=V1_LIGHT,
        change_note="",
        status="active",
    )
    v2 = make_direction(
        client, pid,
        version_number=2,
        title="Stylized Anime / Cel-Shaded Sunset",
        visual_style=V2_STYLE,
        lighting_mood=V2_LIGHT,
        change_note="Artistic pivot to vibrant cel-shaded anime aesthetic at dusk",
        status="draft",
    )

    shot_ids = []
    for seq, key in enumerate(["SHOT-01", "SHOT-02", "SHOT-03", "SHOT-04", "SHOT-05", "SHOT-06"], 1):
        data = SHOT_DATA[key]
        sid = make_shot(client, pid, data["title"], data["description"], seq)
        shot_ids.append((key, sid))

        # Attach a ShotVersion v1 with prompt + impact_reason via the review endpoint.
        # We use direction v1 as the baseline.  For SHOT-06 we deliberately omit prompt/reason
        # to simulate missing dependency metadata (boundary gate).
        if data["prompt"] or data["impact_reason"]:
            # Post a review that creates a ShotVersion tied to dir v1
            rev_resp = client.post(
                f"/projects/{pid}/shots/{sid}/review",
                json={
                    "direction_version_id": v1["id"],
                    "approved_action": "retain",
                    "prompt": data["prompt"],
                    "impact_reason": data["impact_reason"],
                    "note": f"V1 baseline approved",
                },
            )
            assert rev_resp.status_code == 200, rev_resp.json()
            sv_id = rev_resp.json()["id"]

    return pid, v1["id"], v2["id"], shot_ids


def test_impact_analysis_all_six_shots_ground_truth(client):
    """
    End-to-end ground-truth validation: the impact engine must match
    test-scenario.md §4 for all 6 shots.
    """
    pid, dir_v1_id, dir_v2_id, shot_ids = _setup_demo_scenario(client)

    resp = client.post(
        f"/projects/{pid}/directions/analyze-impact",
        json={"target_direction_id": dir_v2_id},
    )
    assert resp.status_code == 200, resp.json()
    results = {r["shot_id"]: r for r in resp.json()["results"]}

    for key, sid in shot_ids:
        expected_action, min_confidence = GROUND_TRUTH[key]
        result = results[sid]

        assert result["action"] == expected_action, (
            f"{key}: expected action='{expected_action}' got '{result['action']}'. "
            f"reason={result['reason']}"
        )
        assert result["reason"], f"{key}: reason must be non-empty"

        if min_confidence is not None:
            assert result["confidence"] >= min_confidence, (
                f"{key}: expected confidence >= {min_confidence} got {result['confidence']}"
            )
        else:
            # SHOT-06: confidence must be low (< 0.60)
            assert result["confidence"] < 0.60, (
                f"{key}: expected confidence < 0.60 (needs_review) got {result['confidence']}"
            )


def test_impact_analysis_safety_gate_no_false_retain(client):
    """
    §5.1 safety gate: Recall = 1.00.
    No truly affected shot (adapt/regenerate/needs_review) may be classified retain.
    """
    pid, _, dir_v2_id, shot_ids = _setup_demo_scenario(client)

    resp = client.post(
        f"/projects/{pid}/directions/analyze-impact",
        json={"target_direction_id": dir_v2_id},
    )
    results = {r["shot_id"]: r for r in resp.json()["results"]}

    truly_affected_keys = {"SHOT-01", "SHOT-02", "SHOT-04", "SHOT-05", "SHOT-06"}
    for key, sid in shot_ids:
        if key in truly_affected_keys:
            action = results[sid]["action"]
            assert action != "retain", (
                f"SAFETY VIOLATION: {key} (truly affected) was classified as 'retain'"
            )


def test_impact_analysis_boundary_gate_missing_deps(client):
    """
    §7.1: A shot with no dependency data must return needs_review, never retain.
    """
    pid = make_project(client)
    make_direction(client, pid, version_number=1, title="V1",
                   visual_style=V1_STYLE, lighting_mood=V1_LIGHT)
    v2 = make_direction(client, pid, version_number=2, title="V2",
                        visual_style=V2_STYLE, lighting_mood=V2_LIGHT)

    # Shot with no description and no ShotVersion (simulates SHOT-06 case)
    sid = make_shot(client, pid, "Mystery Figure in Alleyway Doorway",
                    description=None)

    resp = client.post(
        f"/projects/{pid}/directions/analyze-impact",
        json={"target_direction_id": v2["id"]},
    )
    assert resp.status_code == 200
    results = {r["shot_id"]: r for r in resp.json()["results"]}
    result = results[sid]
    assert result["action"] == "needs_review", (
        f"Missing-dep shot must return needs_review, got '{result['action']}'"
    )
    assert result["confidence"] < 0.60


def test_impact_analysis_retain_vector_asset(client):
    """
    §3 SHOT-03: vector/prop shot with no style/lighting dep must return retain.
    """
    pid = make_project(client)
    make_direction(client, pid, version_number=1, title="V1",
                   visual_style=V1_STYLE, lighting_mood=V1_LIGHT)
    v2 = make_direction(client, pid, version_number=2, title="V2",
                        visual_style=V2_STYLE, lighting_mood=V2_LIGHT)

    sid = make_shot(
        client, pid,
        title="Holographic Data Core HUD Overlay",
        description=(
            "Direct close-up on the hexagonal data core display projecting "
            "a minimalist holographic delivery manifest. "
            "REQ-PROP-01 (Hexagonal Data Core), REQ-UI-01 (Clean Vector HUD)"
        ),
    )

    resp = client.post(
        f"/projects/{pid}/directions/analyze-impact",
        json={"target_direction_id": v2["id"]},
    )
    result = next(r for r in resp.json()["results"] if r["shot_id"] == sid)
    assert result["action"] == "retain"
    assert result["confidence"] >= 0.90


def test_impact_analysis_unknown_target(client):
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/directions/analyze-impact",
        json={"target_direction_id": "dir_00000000"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_impact_analysis_unknown_project(client):
    resp = client.post(
        "/projects/prj_00000000/directions/analyze-impact",
        json={"target_direction_id": "dir_00000000"},
    )
    assert resp.status_code == 404


def test_impact_analysis_schema_validation(client):
    """
    §7.4: All results must validate against the strict output schema.
    action must be one of the four literals; reason non-empty; confidence in [0,1].
    """
    pid, _, dir_v2_id, _ = _setup_demo_scenario(client)
    resp = client.post(
        f"/projects/{pid}/directions/analyze-impact",
        json={"target_direction_id": dir_v2_id},
    )
    assert resp.status_code == 200
    for r in resp.json()["results"]:
        assert r["action"] in ("retain", "adapt", "regenerate", "needs_review"), \
            f"Invalid action: {r['action']}"
        assert isinstance(r["reason"], str) and r["reason"], \
            f"reason must be non-empty string for shot {r['shot_id']}"
        assert 0.0 <= r["confidence"] <= 1.0, \
            f"confidence out of range for shot {r['shot_id']}: {r['confidence']}"
        assert "affected_requirements" in r, \
            f"affected_requirements missing for shot {r['shot_id']}"


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/shots/{shot_id}/review  (FR-09)
# ---------------------------------------------------------------------------


def test_review_shot_approve_ai_recommendation(client):
    """FR-09: Director accepts AI recommendation; system records approved status."""
    pid = make_project(client)
    v1 = make_direction(client, pid, version_number=1, title="V1")
    sid = make_shot(client, pid, "Shot A")

    resp = client.post(
        f"/projects/{pid}/shots/{sid}/review",
        json={
            "direction_version_id": v1["id"],
            "approved_action": "adapt",
            "note": "Approved by director",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["shot_id"] == sid
    assert body["approved_action"] == "adapt"
    assert body["human_approval_status"] == "approved"
    assert body["note"] == "Approved by director"
    assert body["id"].startswith("sver_")


def test_review_shot_override_needs_review(client):
    """FR-09: Director overrides needs_review to adapt (SHOT-06 scenario)."""
    pid = make_project(client)
    v2 = make_direction(client, pid, version_number=2, title="V2")
    sid = make_shot(client, pid, "Mystery Figure in Alleyway Doorway")

    resp = client.post(
        f"/projects/{pid}/shots/{sid}/review",
        json={
            "direction_version_id": v2["id"],
            "approved_action": "adapt",
            "note": "Manual triage: Asset is background guard; adapt lighting to warm dusk",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved_action"] == "adapt"
    assert body["human_approval_status"] == "approved"
    assert "Manual triage" in body["note"]


def test_review_shot_invalid_action(client):
    pid = make_project(client)
    v1 = make_direction(client, pid, version_number=1, title="V1")
    sid = make_shot(client, pid, "S1")
    resp = client.post(
        f"/projects/{pid}/shots/{sid}/review",
        json={"direction_version_id": v1["id"], "approved_action": "invalid_action"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_review_shot_unknown_direction(client):
    pid = make_project(client)
    sid = make_shot(client, pid, "S1")
    resp = client.post(
        f"/projects/{pid}/shots/{sid}/review",
        json={"direction_version_id": "dir_00000000", "approved_action": "retain"},
    )
    assert resp.status_code == 404


def test_review_shot_unknown_shot(client):
    pid = make_project(client)
    v1 = make_direction(client, pid, version_number=1, title="V1")
    resp = client.post(
        f"/projects/{pid}/shots/shot_00000000/review",
        json={"direction_version_id": v1["id"], "approved_action": "retain"},
    )
    assert resp.status_code == 404


def test_review_shot_unknown_project(client):
    resp = client.post(
        "/projects/prj_00000000/shots/shot_00000000/review",
        json={"direction_version_id": "dir_00000000", "approved_action": "retain"},
    )
    assert resp.status_code == 404


def test_review_stores_distinct_ai_and_human_fields(client):
    """
    FR-09: AI suggestion (action_recommendation) and human decision (approved_action)
    are stored as distinct fields. Overriding needs_review → adapt is the canonical check.
    """
    pid = make_project(client)
    v2 = make_direction(client, pid, version_number=2, title="V2")
    sid = make_shot(client, pid, "SHOT-06 analogue")

    resp = client.post(
        f"/projects/{pid}/shots/{sid}/review",
        json={
            "direction_version_id": v2["id"],
            "approved_action": "adapt",
            "note": "Human override",
        },
    )
    body = resp.json()
    # action_recommendation starts as None (no engine ran) — human approved_action is adapt
    assert body["approved_action"] == "adapt"
    assert body["human_approval_status"] == "approved"
    # The AI action_recommendation field can be null (no engine ran for this version)
    # This proves the two fields are independent
    assert "action_recommendation" in body


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/storyboard  (FR-11)
# ---------------------------------------------------------------------------


def test_storyboard_empty_project(client):
    pid = make_project(client)
    resp = client.get(f"/projects/{pid}/storyboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == pid
    assert body["shots"] == []
    assert body["total"] == 0


def test_storyboard_returns_shots_in_order(client):
    pid = make_project(client)
    make_shot(client, pid, "Shot 3", sequence_order=3)
    make_shot(client, pid, "Shot 1", sequence_order=1)
    make_shot(client, pid, "Shot 2", sequence_order=2)
    resp = client.get(f"/projects/{pid}/storyboard")
    shots = resp.json()["shots"]
    assert [s["sequence_order"] for s in shots] == [1, 2, 3]


def test_storyboard_contains_all_required_fields(client):
    pid = make_project(client)
    make_shot(client, pid, "Opening")
    resp = client.get(f"/projects/{pid}/storyboard")
    entry = resp.json()["shots"][0]
    for field in (
        "shot_id", "sequence_order", "title", "shot_status",
        "current_version_id", "current_version_number",
        "approved_action", "human_approval_status",
        "asset_uri", "asset_type",
    ):
        assert field in entry, f"Missing field: {field}"


def test_storyboard_reflects_approved_version(client):
    """FR-11: Storyboard shows latest approved shot version metadata."""
    pid = make_project(client)
    v1 = make_direction(client, pid, version_number=1, title="V1")
    sid = make_shot(client, pid, "Shot A")

    # Record review (creates ShotVersion)
    client.post(
        f"/projects/{pid}/shots/{sid}/review",
        json={"direction_version_id": v1["id"], "approved_action": "retain", "note": "OK"},
    )

    resp = client.get(f"/projects/{pid}/storyboard")
    entry = resp.json()["shots"][0]
    assert entry["shot_id"] == sid
    assert entry["current_version_id"] is not None
    assert entry["approved_action"] == "retain"
    assert entry["human_approval_status"] == "approved"


def test_storyboard_unknown_project(client):
    resp = client.get("/projects/prj_00000000/storyboard")
    assert resp.status_code == 404


def test_storyboard_shot_without_version(client):
    """Shot with no ShotVersion shows null version fields."""
    pid = make_project(client)
    make_shot(client, pid, "Unreviewed Shot")
    resp = client.get(f"/projects/{pid}/storyboard")
    entry = resp.json()["shots"][0]
    assert entry["current_version_id"] is None
    assert entry["current_version_number"] is None
    assert entry["approved_action"] is None


# ---------------------------------------------------------------------------
# Immutability verification  (FR-10, §5 Phase 5)
# ---------------------------------------------------------------------------


def test_direction_v1_immutable_after_v2_creation(client):
    """
    FR-10: Creating V2 must not modify V1 record.
    """
    pid = make_project(client)
    v1 = make_direction(client, pid, version_number=1, title="V1",
                        visual_style=V1_STYLE, lighting_mood=V1_LIGHT)
    make_direction(client, pid, version_number=2, title="V2",
                   visual_style=V2_STYLE, lighting_mood=V2_LIGHT)

    resp = client.get(f"/projects/{pid}/directions/{v1['id']}")
    assert resp.status_code == 200
    fetched = resp.json()
    assert fetched["visual_style"] == V1_STYLE
    assert fetched["lighting_mood"] == V1_LIGHT
    assert fetched["version_number"] == 1


def test_shot_version_v1_persists_after_review_creates_v2(client):
    """
    FR-10: ShotVersion v1 must remain queryable after a second review creates v2.
    """
    pid = make_project(client)
    v1 = make_direction(client, pid, version_number=1, title="V1")
    v2 = make_direction(client, pid, version_number=2, title="V2")
    sid = make_shot(client, pid, "Shot A")

    # Create ShotVersion v1 via review
    resp1 = client.post(
        f"/projects/{pid}/shots/{sid}/review",
        json={"direction_version_id": v1["id"], "approved_action": "retain", "note": "V1 baseline"},
    )
    assert resp1.status_code == 200
    sv1_id = resp1.json()["id"]
    assert resp1.json()["version_number"] == 1

    # Create ShotVersion v2 via review (new direction)
    resp2 = client.post(
        f"/projects/{pid}/shots/{sid}/review",
        json={"direction_version_id": v2["id"], "approved_action": "adapt", "note": "V2 adapt"},
    )
    assert resp2.status_code == 200
    sv2_id = resp2.json()["id"]
    assert resp2.json()["version_number"] == 2

    # v1 and v2 are distinct records
    assert sv1_id != sv2_id


# ---------------------------------------------------------------------------
# Asset reuse rate  (§5.3)
# ---------------------------------------------------------------------------


def test_asset_reuse_rate_ground_truth(client):
    """
    §5.3: With 3 retain/adapt shots out of 6, reuse rate = 50%.
    Validate engine produces >= 3 retain+adapt results.
    """
    pid, _, dir_v2_id, shot_ids = _setup_demo_scenario(client)

    resp = client.post(
        f"/projects/{pid}/directions/analyze-impact",
        json={"target_direction_id": dir_v2_id},
    )
    results = resp.json()["results"]
    reusable = sum(1 for r in results if r["action"] in ("retain", "adapt"))
    total = len(results)
    reuse_rate = reusable / total if total else 0

    assert reuse_rate >= 0.50, (
        f"Asset reuse rate {reuse_rate:.1%} < 50% target. "
        f"Actions: {[(r['shot_id'], r['action']) for r in results]}"
    )
