"""
Tests derived directly from the contract examples in api-projects.md and data-model.md.
"""


# ---------------------------------------------------------------------------
# POST /projects
# ---------------------------------------------------------------------------


def test_create_project_minimal(client):
    """Contract: name required, description optional; returns 201 with Location."""
    resp = client.post("/projects", json={"name": "Demo film"})
    assert resp.status_code == 201
    assert "Location" in resp.headers
    body = resp.json()
    assert body["name"] == "Demo film"
    assert body["description"] is None
    assert body["status"] == "draft"
    assert body["id"].startswith("prj_")
    assert "created_at" in body
    assert "updated_at" in body


def test_create_project_with_description(client):
    """Contract example: POST with name and description."""
    resp = client.post(
        "/projects",
        json={"name": "Demo film", "description": "Six-shot direction-change demo"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Demo film"
    assert body["description"] == "Six-shot direction-change demo"
    assert body["status"] == "draft"
    location = resp.headers["Location"]
    assert location == f"/projects/{body['id']}"


def test_create_project_status_defaults_to_draft(client):
    """D-001 #6: server always defaults status to draft."""
    resp = client.post("/projects", json={"name": "My Project"})
    assert resp.json()["status"] == "draft"


def test_create_project_status_not_accepted(client):
    """D-001 #6: status is rejected on create."""
    resp = client.post("/projects", json={"name": "X", "status": "active"})
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert any(f["field"] == "status" for f in err["fields"])


def test_create_project_missing_name(client):
    """Contract: missing required name -> 400 validation_error with field info."""
    resp = client.post("/projects", json={"description": "No name"})
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert err["message"] == "Project input is invalid"
    assert any(f["field"] == "name" for f in err["fields"])


def test_create_project_blank_name(client):
    """D-001 #7: whitespace-only name is rejected."""
    resp = client.post("/projects", json={"name": "   "})
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "validation_error"


def test_create_project_name_too_long(client):
    """D-001 #7: name max 100 chars."""
    resp = client.post("/projects", json={"name": "x" * 101})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_project_description_too_long(client):
    """D-001 #7: description max 500 chars."""
    resp = client.post("/projects", json={"name": "Valid", "description": "d" * 501})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_project_invalid_json(client):
    """Contract: invalid JSON body -> 400."""
    resp = client.post(
        "/projects",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_project_name_trimmed(client):
    """D-001 #7: name is trimmed before storage."""
    resp = client.post("/projects", json={"name": "  Film  "})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Film"


def test_create_project_duplicate_names_allowed(client):
    """D-001 #9: duplicate names are allowed; IDs differ."""
    r1 = client.post("/projects", json={"name": "Same"})
    r2 = client.post("/projects", json={"name": "Same"})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


def test_create_project_id_stable(client):
    """Contract: ID is generated once and never changes."""
    resp = client.post("/projects", json={"name": "Stable"})
    pid = resp.json()["id"]
    get_resp = client.get(f"/projects/{pid}")
    assert get_resp.json()["id"] == pid


# ---------------------------------------------------------------------------
# GET /projects
# ---------------------------------------------------------------------------


def test_list_projects_empty(client):
    """Contract: list on empty db returns items=[], total=0."""
    resp = client.get("/projects")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_list_projects_returns_all_fields(client):
    """Contract: list item has all project fields."""
    client.post("/projects", json={"name": "Demo film", "description": "Six-shot direction-change demo"})
    resp = client.get("/projects")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    for key in ("id", "name", "description", "status", "created_at", "updated_at"):
        assert key in item


def test_list_projects_total(client):
    """Contract: total reflects actual count."""
    client.post("/projects", json={"name": "A"})
    client.post("/projects", json={"name": "B"})
    resp = client.get("/projects")
    assert resp.json()["total"] == 2


def test_list_projects_default_pagination(client):
    """D-001 #8: default limit=20, offset=0."""
    resp = client.get("/projects")
    body = resp.json()
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_list_projects_custom_limit(client):
    """D-001 #8: custom limit and offset are echoed back."""
    resp = client.get("/projects?limit=5&offset=10")
    body = resp.json()
    assert body["limit"] == 5
    assert body["offset"] == 10


def test_list_projects_sorted_desc(client):
    """Contract: sorted by created_at descending."""
    import time

    client.post("/projects", json={"name": "First"})
    time.sleep(0.05)
    client.post("/projects", json={"name": "Second"})
    resp = client.get("/projects")
    items = resp.json()["items"]
    assert items[0]["name"] == "Second"
    assert items[1]["name"] == "First"


def test_list_projects_limit_max(client):
    """D-001 #8: limit max is 100; above that -> 400."""
    resp = client.get("/projects?limit=101")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_list_projects_pagination_offset(client):
    """D-001 #8: offset skips records."""
    for i in range(3):
        client.post("/projects", json={"name": f"P{i}"})
    resp = client.get("/projects?limit=2&offset=1")
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3


# ---------------------------------------------------------------------------
# GET /projects/{project_id}
# ---------------------------------------------------------------------------


def test_get_project(client):
    """Contract: get returns full project representation."""
    create = client.post("/projects", json={"name": "Demo film", "description": "Six-shot direction-change demo"})
    pid = create.json()["id"]
    resp = client.get(f"/projects/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == pid
    assert body["name"] == "Demo film"
    assert body["status"] == "draft"


def test_get_project_not_found(client):
    """Contract: unknown ID -> 404 with standard error body."""
    resp = client.get("/projects/prj_00000000")
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "not_found"
    assert err["message"] == "Project not found"
    assert err["fields"] == []


# ---------------------------------------------------------------------------
# Error body shape
# ---------------------------------------------------------------------------


def test_error_body_shape_400(client):
    """Contract: 400 error body has code, message, fields."""
    resp = client.post("/projects", json={})
    err = resp.json()["error"]
    assert "code" in err
    assert "message" in err
    assert isinstance(err["fields"], list)


def test_error_body_shape_404(client):
    """Contract: 404 error body has code, message, fields=[]."""
    resp = client.get("/projects/prj_nonexistent")
    err = resp.json()["error"]
    assert err["code"] == "not_found"
    assert isinstance(err["fields"], list)
    assert err["fields"] == []
