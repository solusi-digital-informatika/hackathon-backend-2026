"""
Tests derived directly from the contract examples in api-shots.md, data-model.md, and D-003.md.
"""
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_project(client, name="Test Project"):
    resp = client.post("/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/shots
# ---------------------------------------------------------------------------


def test_create_shot_minimal(client):
    """Contract: title required, description/sequence_order optional; returns 201."""
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/shots", json={"title": "Opening"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Opening"
    assert body["description"] is None
    assert body["status"] == "draft"
    assert body["project_id"] == pid
    assert body["id"].startswith("shot_")
    assert body["sequence_order"] == 1
    assert "created_at" in body
    assert "updated_at" in body


def test_create_shot_with_all_fields(client):
    """Contract example from api-shots.md: POST with title, description, sequence_order."""
    pid = make_project(client)
    resp = client.post(
        f"/projects/{pid}/shots",
        json={"title": "Establishing Aerial Alleyway", "description": "Wide crane shot", "sequence_order": 1},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Establishing Aerial Alleyway"
    assert body["description"] == "Wide crane shot"
    assert body["sequence_order"] == 1
    location = resp.headers.get("Location", "")
    assert location == f"/projects/{pid}/shots/{body['id']}"


def test_create_shot_status_defaults_to_draft(client):
    """D-003: server always defaults status to draft."""
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    assert resp.json()["status"] == "draft"


def test_create_shot_sequence_order_auto_assigned(client):
    """D-003: sequence_order is auto-assigned as max+1 when omitted."""
    pid = make_project(client)
    r1 = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    r2 = client.post(f"/projects/{pid}/shots", json={"title": "S2"})
    assert r1.json()["sequence_order"] == 1
    assert r2.json()["sequence_order"] == 2


def test_create_shot_explicit_sequence_order(client):
    """Contract: explicit sequence_order is used as-is."""
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/shots", json={"title": "S1", "sequence_order": 5})
    assert resp.json()["sequence_order"] == 5


def test_create_shot_missing_title(client):
    """Contract: missing required title -> 400 validation_error."""
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/shots", json={"description": "no title"})
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert any(f["field"] == "title" for f in err["fields"])


def test_create_shot_blank_title(client):
    """D-003: whitespace-only title is rejected."""
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/shots", json={"title": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_shot_title_too_long(client):
    """data-model.md: title max 100 chars."""
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/shots", json={"title": "x" * 101})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_shot_description_too_long(client):
    """data-model.md: description max 1000 chars."""
    pid = make_project(client)
    resp = client.post(f"/projects/{pid}/shots", json={"title": "S1", "description": "d" * 1001})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_shot_unknown_project(client):
    """D-003: unknown project_id -> 404."""
    resp = client.post("/projects/prj_00000000/shots", json={"title": "S1"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_create_shot_project_isolation(client):
    """D-003: shots from project A do not appear under project B."""
    pid_a = make_project(client, "A")
    pid_b = make_project(client, "B")
    client.post(f"/projects/{pid_a}/shots", json={"title": "Shot A"})
    resp = client.get(f"/projects/{pid_b}/shots")
    assert resp.json()["items"] == []


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/shots
# ---------------------------------------------------------------------------


def test_list_shots_empty(client):
    """Contract: list on project with no shots returns items=[], total=0."""
    pid = make_project(client)
    resp = client.get(f"/projects/{pid}/shots")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_shots_returns_all_fields(client):
    """Contract: list item has all shot fields."""
    pid = make_project(client)
    client.post(f"/projects/{pid}/shots", json={"title": "S1", "description": "Desc"})
    resp = client.get(f"/projects/{pid}/shots")
    item = resp.json()["items"][0]
    for key in ("id", "project_id", "sequence_order", "title", "description", "status", "created_at", "updated_at"):
        assert key in item


def test_list_shots_sorted_by_sequence_order(client):
    """Contract: list returns shots ordered by sequence_order ascending."""
    pid = make_project(client)
    client.post(f"/projects/{pid}/shots", json={"title": "Third", "sequence_order": 3})
    client.post(f"/projects/{pid}/shots", json={"title": "First", "sequence_order": 1})
    client.post(f"/projects/{pid}/shots", json={"title": "Second", "sequence_order": 2})
    resp = client.get(f"/projects/{pid}/shots")
    items = resp.json()["items"]
    assert items[0]["title"] == "First"
    assert items[1]["title"] == "Second"
    assert items[2]["title"] == "Third"


def test_list_shots_total_count(client):
    """Contract: total reflects actual shot count."""
    pid = make_project(client)
    client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    client.post(f"/projects/{pid}/shots", json={"title": "S2"})
    resp = client.get(f"/projects/{pid}/shots")
    assert resp.json()["total"] == 2


def test_list_shots_unknown_project(client):
    """D-003: unknown project_id -> 404."""
    resp = client.get("/projects/prj_00000000/shots")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/shots/{shot_id}
# ---------------------------------------------------------------------------


def test_get_shot(client):
    """Contract: get returns full shot representation."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1", "description": "Desc"})
    sid = create.json()["id"]
    resp = client.get(f"/projects/{pid}/shots/{sid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == sid
    assert body["title"] == "S1"
    assert body["project_id"] == pid


def test_get_shot_not_found(client):
    """Contract: unknown shot_id -> 404."""
    pid = make_project(client)
    resp = client.get(f"/projects/{pid}/shots/shot_00000000")
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "not_found"
    assert err["fields"] == []


def test_get_shot_unknown_project(client):
    """D-003: unknown project_id -> 404."""
    resp = client.get("/projects/prj_00000000/shots/shot_00000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_get_shot_isolation_across_projects(client):
    """D-003: shot from project A is not accessible via project B's path."""
    pid_a = make_project(client, "A")
    pid_b = make_project(client, "B")
    create = client.post(f"/projects/{pid_a}/shots", json={"title": "Shot A"})
    sid = create.json()["id"]
    resp = client.get(f"/projects/{pid_b}/shots/{sid}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /projects/{project_id}/shots/{shot_id}
# ---------------------------------------------------------------------------


def test_update_shot_title(client):
    """Contract: PATCH can update title."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "Original"})
    sid = create.json()["id"]
    resp = client.patch(f"/projects/{pid}/shots/{sid}", json={"title": "Updated title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated title"


def test_update_shot_description(client):
    """Contract: PATCH can update description."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    sid = create.json()["id"]
    resp = client.patch(f"/projects/{pid}/shots/{sid}", json={"description": "Updated description"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description"


def test_update_shot_status(client):
    """Contract: PATCH can update status to valid enum value."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    sid = create.json()["id"]
    resp = client.patch(f"/projects/{pid}/shots/{sid}", json={"status": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


def test_update_shot_sequence_order(client):
    """Contract: PATCH can update sequence_order."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    sid = create.json()["id"]
    resp = client.patch(f"/projects/{pid}/shots/{sid}", json={"sequence_order": 10})
    assert resp.status_code == 200
    assert resp.json()["sequence_order"] == 10


def test_update_shot_all_fields(client):
    """Contract example: PATCH with all updatable fields."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    sid = create.json()["id"]
    resp = client.patch(
        f"/projects/{pid}/shots/{sid}",
        json={"title": "Updated title", "description": "Updated description", "status": "in_review", "sequence_order": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Updated title"
    assert body["description"] == "Updated description"
    assert body["status"] == "in_review"
    assert body["sequence_order"] == 2


def test_update_shot_invalid_status(client):
    """Contract: invalid status enum -> 400."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    sid = create.json()["id"]
    resp = client.patch(f"/projects/{pid}/shots/{sid}", json={"status": "not_a_status"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_update_shot_not_found(client):
    """Contract: unknown shot_id -> 404."""
    pid = make_project(client)
    resp = client.patch(f"/projects/{pid}/shots/shot_00000000", json={"title": "X"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_update_shot_unknown_project(client):
    """D-003: unknown project_id -> 404."""
    resp = client.patch("/projects/prj_00000000/shots/shot_00000000", json={"title": "X"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# DELETE /projects/{project_id}/shots/{shot_id}
# ---------------------------------------------------------------------------


def test_delete_shot(client):
    """Contract: DELETE returns 204 and shot is gone."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    sid = create.json()["id"]
    resp = client.delete(f"/projects/{pid}/shots/{sid}")
    assert resp.status_code == 204
    # Verify it's gone
    get_resp = client.get(f"/projects/{pid}/shots/{sid}")
    assert get_resp.status_code == 404


def test_delete_shot_not_found(client):
    """Contract: unknown shot_id -> 404."""
    pid = make_project(client)
    resp = client.delete(f"/projects/{pid}/shots/shot_00000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_delete_shot_unknown_project(client):
    """D-003: unknown project_id -> 404."""
    resp = client.delete("/projects/prj_00000000/shots/shot_00000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_delete_shot_removes_from_list(client):
    """After deletion, shot no longer appears in list."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    sid = create.json()["id"]
    client.delete(f"/projects/{pid}/shots/{sid}")
    resp = client.get(f"/projects/{pid}/shots")
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


# ---------------------------------------------------------------------------
# Stable IDs
# ---------------------------------------------------------------------------


def test_shot_id_stable(client):
    """FR-04: shot ID is generated once and never changes."""
    pid = make_project(client)
    create = client.post(f"/projects/{pid}/shots", json={"title": "S1"})
    sid = create.json()["id"]
    get_resp = client.get(f"/projects/{pid}/shots/{sid}")
    assert get_resp.json()["id"] == sid
