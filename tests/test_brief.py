"""
Tests for Brief ingestion, extraction, retrieval, and human update endpoints.
Derived from contracts/api-brief.md and decisions/D-005.md.
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BRIEF_TEXT = """\
Objective: Courier transporting encrypted data core across a futuristic metropolis.

Art Style: Realistic Cinematic Cyberpunk

Lighting: Moody cool blue lighting, wet asphalt reflections

Characters:
- Aria: athletic build, dark undercut, cybernetic left eye

Key Props:
- Data Core: hexagonal encrypted slate

Constraints:
- No confidential footage
- Cool blue color palette

Unresolved Questions:
- Is rain present in all shots?
"""


def make_project(client, name="Brief Test Project"):
    resp = client.post("/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def ingest(client, pid, text=BRIEF_TEXT, source_name="CyberPulse Creative Brief v1"):
    resp = client.post(
        f"/projects/{pid}/brief/ingest",
        json={"source_name": source_name, "content": text},
    )
    assert resp.status_code == 201
    return resp.json()


def extract(client, pid):
    resp = client.post(f"/projects/{pid}/brief/extract")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/brief/ingest
# ---------------------------------------------------------------------------


def test_ingest_returns_201_and_source_doc(client):
    """Contract: ingest returns 201 with SourceDocument metadata."""
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/brief/ingest",
        json={"source_name": "CyberPulse Creative Brief v1", "content": BRIEF_TEXT},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("doc_")
    assert body["project_id"] == pid
    assert body["source_name"] == "CyberPulse Creative Brief v1"
    assert body["content"] == BRIEF_TEXT.strip()
    assert "created_at" in body


def test_ingest_missing_source_name(client):
    """Contract: missing required source_name -> 400 validation_error."""
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/brief/ingest",
        json={"content": BRIEF_TEXT},
    )
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert any(f["field"] == "source_name" for f in err["fields"])


def test_ingest_missing_content(client):
    """Contract: missing required content -> 400 validation_error."""
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/brief/ingest",
        json={"source_name": "Brief v1"},
    )
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert any(f["field"] == "content" for f in err["fields"])


def test_ingest_blank_source_name(client):
    """D-005: whitespace-only source_name is rejected."""
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/brief/ingest",
        json={"source_name": "   ", "content": BRIEF_TEXT},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_ingest_blank_content(client):
    """D-005: whitespace-only content is rejected."""
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/brief/ingest",
        json={"source_name": "Brief v1", "content": "   "},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_ingest_unknown_project(client):
    """Contract: unknown project_id -> 404."""
    resp = client.post(
        "/projects/prj_00000000/brief/ingest",
        json={"source_name": "Brief", "content": BRIEF_TEXT},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_ingest_stable_doc_id(client):
    """D-005: source document ID is stable (doc_ prefix)."""
    pid = make_project(client)
    body = ingest(client, pid)
    assert body["id"].startswith("doc_")


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/brief/extract
# ---------------------------------------------------------------------------


def test_extract_returns_structured_brief(client):
    """Contract: extract returns structured ProjectBrief with all fields."""
    pid = make_project(client)
    ingest(client, pid)
    body = extract(client, pid)

    assert body["id"].startswith("brief_")
    assert body["project_id"] == pid
    assert body["review_status"] == "pending_review"
    assert "objective" in body
    assert "visual_style" in body
    assert "lighting_mood" in body
    assert isinstance(body["characters"], list)
    assert isinstance(body["key_props"], list)
    assert isinstance(body["constraints"], list)
    assert isinstance(body["unresolved_questions"], list)
    assert "created_at" in body
    assert "updated_at" in body


def test_extract_captures_objective(client):
    """Extraction: objective field is populated from brief text."""
    pid = make_project(client)
    ingest(client, pid)
    body = extract(client, pid)
    assert "courier" in body["objective"].lower() or "data core" in body["objective"].lower()


def test_extract_captures_visual_style(client):
    """Extraction: visual_style is populated."""
    pid = make_project(client)
    ingest(client, pid)
    body = extract(client, pid)
    assert body["visual_style"] != ""


def test_extract_captures_characters(client):
    """Extraction: characters list is non-empty and has name/details."""
    pid = make_project(client)
    ingest(client, pid)
    body = extract(client, pid)
    assert len(body["characters"]) >= 1
    char = body["characters"][0]
    assert "name" in char
    assert "details" in char
    assert char["name"] != ""


def test_extract_captures_constraints(client):
    """Extraction: constraints list is non-empty."""
    pid = make_project(client)
    ingest(client, pid)
    body = extract(client, pid)
    assert len(body["constraints"]) >= 1


def test_extract_captures_unresolved_questions(client):
    """Extraction: unresolved_questions list is non-empty."""
    pid = make_project(client)
    ingest(client, pid)
    body = extract(client, pid)
    assert len(body["unresolved_questions"]) >= 1


def test_extract_no_source_doc(client):
    """Contract: extract without prior ingest -> 404."""
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/brief/extract")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_extract_unknown_project(client):
    """Contract: unknown project_id -> 404."""
    resp = client.post("/projects/prj_00000000/brief/extract")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_extract_source_document_id_linked(client):
    """D-005: brief.source_document_id references the ingested doc."""
    pid = make_project(client)
    doc_body = ingest(client, pid)
    brief_body = extract(client, pid)
    assert brief_body["source_document_id"] == doc_body["id"]


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/brief
# ---------------------------------------------------------------------------


def test_get_brief_returns_source_and_structured(client):
    """Contract: GET returns source_document and brief fields."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    resp = client.get(f"/projects/{pid}/brief")
    assert resp.status_code == 200
    body = resp.json()
    assert "source_document" in body
    assert "brief" in body
    assert body["source_document"]["project_id"] == pid
    assert body["brief"]["project_id"] == pid


def test_get_brief_not_found(client):
    """Contract: GET when no brief exists -> 404."""
    pid = make_project(client)
    resp = client.get(f"/projects/{pid}/brief")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_get_brief_unknown_project(client):
    """Contract: unknown project_id -> 404."""
    resp = client.get("/projects/prj_00000000/brief")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_get_brief_project_isolation(client):
    """D-005: brief from project A is not accessible via project B."""
    pid_a = make_project(client, "A")
    pid_b = make_project(client, "B")
    ingest(client, pid_a)
    extract(client, pid_a)
    resp = client.get(f"/projects/{pid_b}/brief")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /projects/{project_id}/brief
# ---------------------------------------------------------------------------


def test_update_brief_review_status_approved(client):
    """Contract: human can set review_status to approved."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    resp = client.put(f"/projects/{pid}/brief", json={"review_status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "approved"


def test_update_brief_objective(client):
    """Contract: human can update objective."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    resp = client.put(
        f"/projects/{pid}/brief",
        json={"objective": "Revised objective for the project"},
    )
    assert resp.status_code == 200
    assert resp.json()["objective"] == "Revised objective for the project"


def test_update_brief_visual_style(client):
    """Contract: human can update visual_style."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    resp = client.put(
        f"/projects/{pid}/brief",
        json={"visual_style": "Stylized Anime Cel-Shaded"},
    )
    assert resp.status_code == 200
    assert resp.json()["visual_style"] == "Stylized Anime Cel-Shaded"


def test_update_brief_lighting_mood(client):
    """Contract: human can update lighting_mood."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    resp = client.put(
        f"/projects/{pid}/brief",
        json={"lighting_mood": "Warm golden hour amber"},
    )
    assert resp.status_code == 200
    assert resp.json()["lighting_mood"] == "Warm golden hour amber"


def test_update_brief_characters(client):
    """Contract: human can update characters list."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    new_chars = [{"name": "Aria", "details": "Updated character description"}]
    resp = client.put(f"/projects/{pid}/brief", json={"characters": new_chars})
    assert resp.status_code == 200
    chars = resp.json()["characters"]
    assert len(chars) == 1
    assert chars[0]["name"] == "Aria"
    assert chars[0]["details"] == "Updated character description"


def test_update_brief_constraints(client):
    """Contract: human can update constraints list."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    resp = client.put(
        f"/projects/{pid}/brief",
        json={"constraints": ["No confidential footage", "Warm color palette only"]},
    )
    assert resp.status_code == 200
    assert len(resp.json()["constraints"]) == 2


def test_update_brief_all_fields(client):
    """Contract: human can update all fields including approval in one PUT."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    resp = client.put(
        f"/projects/{pid}/brief",
        json={
            "objective": "Final approved objective",
            "visual_style": "Cinematic Realism",
            "lighting_mood": "Cool night tones",
            "characters": [{"name": "Aria", "details": "Final spec"}],
            "key_props": [{"name": "Data Core", "details": "Hexagonal slate"}],
            "constraints": ["No rain in final shots"],
            "unresolved_questions": [],
            "review_status": "approved",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "approved"
    assert body["objective"] == "Final approved objective"
    assert body["unresolved_questions"] == []


def test_update_brief_invalid_review_status(client):
    """Contract: invalid review_status value -> 400."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)
    resp = client.put(f"/projects/{pid}/brief", json={"review_status": "not_valid"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_update_brief_not_found(client):
    """Contract: PUT when no brief exists -> 404."""
    pid = make_project(client)
    resp = client.put(f"/projects/{pid}/brief", json={"review_status": "approved"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_update_brief_unknown_project(client):
    """Contract: unknown project_id -> 404."""
    resp = client.put("/projects/prj_00000000/brief", json={"review_status": "approved"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_update_brief_partial_update_preserves_other_fields(client):
    """D-005: PUT only changes provided fields; others are preserved."""
    pid = make_project(client)
    ingest(client, pid)
    extract(client, pid)

    # First set a known objective
    client.put(f"/projects/{pid}/brief", json={"objective": "Initial objective"})

    # Now update only review_status
    resp = client.put(f"/projects/{pid}/brief", json={"review_status": "approved"})
    assert resp.status_code == 200
    body = resp.json()
    # Objective must still be the value set in the previous PUT
    assert body["objective"] == "Initial objective"
    assert body["review_status"] == "approved"


# ---------------------------------------------------------------------------
# Stable IDs
# ---------------------------------------------------------------------------


def test_brief_id_stable(client):
    """D-005: brief ID is generated once and never changes across GET."""
    pid = make_project(client)
    ingest(client, pid)
    extract_body = extract(client, pid)
    brief_id = extract_body["id"]

    get_resp = client.get(f"/projects/{pid}/brief")
    assert get_resp.status_code == 200
    assert get_resp.json()["brief"]["id"] == brief_id


def test_doc_id_stable(client):
    """D-005: source document ID is generated once and never changes."""
    pid = make_project(client)
    ingest_body = ingest(client, pid)
    doc_id = ingest_body["id"]

    extract(client, pid)
    get_resp = client.get(f"/projects/{pid}/brief")
    assert get_resp.status_code == 200
    assert get_resp.json()["source_document"]["id"] == doc_id
