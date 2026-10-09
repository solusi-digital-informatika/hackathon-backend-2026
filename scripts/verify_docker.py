"""Read-only API check plus an automatically removed storage write probe.

From workspace root (PowerShell):
Get-Content -Raw backend/scripts/verify_docker.py | docker compose exec -T api python -
"""
import json
import tempfile
import urllib.request


def read(path):
    with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=5) as response:
        return response.status, response.read()


status, body = read("/health")
assert status == 200
print("Health:", json.loads(body))
assert read("/docs")[0] == 200
_, body = read("/openapi.json")
paths = json.loads(body)["paths"]
assert "/projects/{project_id}/moodboards/{board_id}/sources" in paths
assert "/projects/{project_id}/moodboards/{board_id}/exports/{export_id}" in paths
with tempfile.TemporaryFile(dir="/app/data/moodboards") as probe:
    probe.write(b"storage-check")
    probe.seek(0)
    assert probe.read() == b"storage-check"
print("Swagger, moodboard routes, and persistent storage: OK")
