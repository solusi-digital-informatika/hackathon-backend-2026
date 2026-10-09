import copy
import io
import json
import time

import httpx
import pytest
from PIL import Image

from app.core.config import settings
from app.modules.moodboards.provider import ProviderError, VisionProvider, validate_translation, parse_output
from app.modules.moodboards.schemas import HumanSummary
from app.modules.moodboards.storage import InvalidImage, prepare_image


def summary(prefix="G1", conflict=False):
    ref = prefix + "-P1"
    return {
        "status_analisis": "cukup_jelas", "status_panduan": "usulan_perlu_konfirmasi",
        "ringkasan_visual": "Dedaunan hijau dengan aksen kuning.",
        "referensi": [{"id": ref, "lokasi": "seluruh gambar", "deskripsi_singkat": "Dedaunan"}],
        "gaya_utama": {"deskripsi": "Botanical", "ciri_utama": ["Organik"], "dasar": "interpretasi",
                       "referensi": [ref], "keyakinan": "tinggi"},
        "nuansa": [{"nama": "Segar", "penyebab_visual": "Dedaunan hijau", "dasar": "interpretasi",
                    "referensi": [ref], "keyakinan": "tinggi"}],
        "palet_warna": [{"warna": "Hijau", "hex_perkiraan": "#70B342", "peran_visual": "Dominan", "referensi": [ref]}],
        "elemen_visual": {"tekstur_dan_material": ["Serat daun"], "pencahayaan": ["Lembut"],
            "bentuk_dan_garis": [], "komposisi_dan_ruang": [], "subjek_dan_latar": ["Tanaman"], "tipografi": []},
        "kelompok_visual": [],
        "panduan_bersama": {"gunakan": [{"arahan": "Gunakan warna hijau", "alasan": "Botanical", "referensi": [ref]}],
                            "hindari": []},
        "perbedaan_atau_konflik": [{"deskripsi": "Hangat versus dingin", "referensi": [ref]}] if conflict else [],
        "pertanyaan_klarifikasi": ["Rasio aspek belum ditentukan"], "keterbatasan": ["HEX perkiraan"],
    }


def image_bytes(color="green", size=(300, 300), format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format)
    return output.getvalue()


@pytest.fixture(autouse=True)
def configure_moodboards(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "moodboard_storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "ai_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "ai_vision_model", "test-model")
    monkeypatch.setattr(VisionProvider, "analyze", lambda self, source, context: summary(source["prefix"]))
    monkeypatch.setattr(VisionProvider, "translate", lambda self, value: {**copy.deepcopy(value), "ringkasan_visual": "Green foliage with yellow accents."})
    monkeypatch.setattr(VisionProvider, "translate_texts", lambda self, texts: ["English: " + t for t in texts])


def create_board(client):
    project = client.post("/projects", json={"name": "Moodboard Project"}).json()
    base = f"/projects/{project['id']}/moodboards"
    response = client.post(base, json={"title": "Botanical", "context": "Warna dari referensi"})
    assert response.status_code == 201
    return base, response.json()


def upload(client, base, board, data=None):
    response = client.post(f"{base}/{board['id']}/sources", data={"revision": board["revision"]},
                           files={"files": ("reference.png", data or image_bytes(), "image/png")})
    assert response.status_code == 201
    return response.json()


def analyze(client, base, board, revision, key="analysis-1"):
    response = client.post(f"{base}/{board['id']}/analyses", json={"revision": revision},
                           headers={"Idempotency-Key": key})
    assert response.status_code == 202, response.text
    return response.json()


def wait_for(client, url):
    for _ in range(300):
        result = client.get(url).json()
        if result["job_status"] not in {"queued", "running"}:
            return result
        time.sleep(0.01)
    pytest.fail("Analysis did not finish")


def completed(client):
    base, board = create_board(client)
    uploaded = upload(client, base, board)
    version = analyze(client, base, board, uploaded["revision"])
    url = f"{base}/{board['id']}/versions/{version['id']}"
    result = wait_for(client, url)
    assert result["job_status"] == "succeeded", result
    return base, board, url, result


def approve_all(client, url, version):
    decisions = [{"finding_id": f["id"], "decision": "accepted", "strength": "prefer"}
                 for f in version["findings"]]
    review = client.patch(url + "/review", json={"revision": version["revision"], "decisions": decisions})
    assert review.status_code == 200, review.text
    response = client.post(url + "/approve", json={"revision": review.json()["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_full_upload_review_export_flow(client):
    base, board, url, version = completed(client)
    assert set(version["human_summary"]) == set(summary())
    assert version["human_summary"]["status_panduan"] == "usulan_perlu_konfirmasi"
    assert client.post(url + "/approve", json={"revision": 1}).status_code == 409
    approved = approve_all(client, url, version)
    assert approved["human_summary"]["status_panduan"] == "dikonfirmasi_manusia"
    exported = client.post(url + "/exports", json={"language": "id"}, headers={"Idempotency-Key": "export-1"})
    assert exported.status_code == 201
    artifact = exported.json()
    response = client.get(f"{base}/{board['id']}/exports/{artifact['id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "Confirmed Constraints" in response.text
    assert "Rasio aspek belum ditentukan" in response.text
    assert "AI_API_KEY" not in response.text and "analysis_key" not in response.text
    again = client.post(url + "/exports", json={"language": "id"}, headers={"Idempotency-Key": "export-1"}).json()
    assert again["id"] == artifact["id"] and again["content_hash"] == artifact["content_hash"]


def test_invalid_images_and_duplicate_do_not_remove_valid_source(client):
    base, board = create_board(client)
    response = client.post(f"{base}/{board['id']}/sources", data={"revision": 1}, files=[
        ("files", ("valid.png", image_bytes(), "image/png")),
        ("files", ("duplicate.png", image_bytes(), "image/png")),
        ("files", ("bad.png", b"not an image", "image/png")),
    ])
    assert [r["status"] for r in response.json()["items"]] == ["created", "duplicate", "rejected"]
    assert len(client.get(f"{base}/{board['id']}").json()["sources"]) == 1


def test_project_isolation_for_sources_versions_exports(client):
    base, board, url, version = completed(client)
    other = client.post("/projects", json={"name": "Other"}).json()["id"]
    foreign = f"/projects/{other}/moodboards/{board['id']}"
    assert client.get(foreign).status_code == 404
    assert client.get(foreign + "/versions/" + version["id"]).status_code == 404
    source = client.get(f"{base}/{board['id']}").json()["sources"][0]
    assert client.get(foreign + "/sources/" + source["id"] + "/file").status_code == 404


def test_stale_revision_and_missing_idempotency(client):
    base, board = create_board(client)
    uploaded = upload(client, base, board)
    assert client.patch(f"{base}/{board['id']}", json={"revision": 1, "title": "Stale"}).status_code == 409
    assert client.post(f"{base}/{board['id']}/analyses", json={"revision": uploaded["revision"]}).status_code == 400


def test_analysis_idempotency_and_versions_preserve_previous(client):
    base, board, url, version = completed(client)
    repeated = analyze(client, base, board, 2)
    assert repeated["id"] == version["id"]
    approve_all(client, url, version)
    original = client.get(url).json()
    current = client.get(f"{base}/{board['id']}").json()
    new_version = analyze(client, base, board, current["revision"], key="analysis-2")
    newer = wait_for(client, f"{base}/{board['id']}/versions/{new_version['id']}")
    assert newer["version_number"] == 2 and newer["review_status"] == "in_review"
    assert client.get(url).json() == original
    assert client.patch(url + "/review", json={"revision": original["revision"]}).status_code == 409


def test_edit_reject_and_human_instruction(client):
    base, board, url, version = completed(client)
    decisions = [{"finding_id": f["id"], "decision": "accepted"} for f in version["findings"]]
    decisions[0] = {"finding_id": version["findings"][0]["id"], "decision": "edited", "value": "Arahan dikoreksi manusia"}
    color_index = next(i for i, f in enumerate(version["findings"]) if f["category"] == "palet_warna")
    decisions[color_index] = {"finding_id": version["findings"][color_index]["id"], "decision": "rejected"}
    result = client.patch(url + "/review", json={"revision": 1, "decisions": decisions,
        "instructions": [{"text": "Jangan ubah identitas karakter", "strength": "must"}]})
    assert result.status_code == 200, result.text
    assert result.json()["human_summary"]["palet_warna"] == []
    assert result.json()["original_result"]["palet_warna"] != []
    assert result.json()["human_summary"]["ringkasan_visual"] == "Arahan dikoreksi manusia"
    assert client.post(url + "/approve", json={"revision": result.json()["revision"]}).status_code == 200
    artifact = client.post(url + "/exports", json={"language": "id"}, headers={"Idempotency-Key": "edited"}).json()
    assert "Jangan ubah identitas karakter" in artifact["content"]
    assert "#70B342" not in artifact["content"]


def test_unknown_reference_edit_is_rejected(client):
    _, _, url, version = completed(client)
    style = copy.deepcopy(version["original_result"]["gaya_utama"])
    style["referensi"] = ["G9-P9"]
    result = client.patch(url + "/review", json={"revision": 1, "decisions": [
        {"finding_id": "F-002", "decision": "edited", "value": style}]})
    assert result.status_code == 400
    assert client.get(url).json()["revision"] == 1


def test_conflict_blocks_approval_until_resolution(client, monkeypatch):
    monkeypatch.setattr(VisionProvider, "analyze", lambda self, source, context: summary(source["prefix"], True))
    _, _, url, version = completed(client)
    result = client.patch(url + "/review", json={"revision": 1, "decisions": [
        {"finding_id": f["id"], "decision": "accepted"} for f in version["findings"]]}).json()
    assert client.post(url + "/approve", json={"revision": result["revision"]}).status_code == 409
    result = client.patch(url + "/review", json={"revision": result["revision"],
        "conflict_resolutions": {"0": "Tetap unknown, bukan constraint"}}).json()
    assert client.post(url + "/approve", json={"revision": result["revision"]}).status_code == 200


def test_english_export_requires_preview_confirmation(client):
    base, board, url, version = completed(client)
    approve_all(client, url, version)
    result = client.post(url + "/exports", json={"language": "en"}, headers={"Idempotency-Key": "english"})
    assert result.status_code == 201, result.text
    artifact = result.json()
    assert artifact["status"] == "pending_confirmation"
    download = f"{base}/{board['id']}/exports/{artifact['id']}"
    assert client.get(download).status_code == 409
    assert client.post(download + "/confirm").status_code == 200
    assert "Green foliage" in client.get(download).text


def test_unconfigured_provider_does_not_fake_analysis(client, monkeypatch):
    base, board = create_board(client)
    result = upload(client, base, board)
    monkeypatch.setattr(settings, "ai_api_key", "")
    response = client.post(f"{base}/{board['id']}/analyses", json={"revision": result["revision"]},
                           headers={"Idempotency-Key": "no-key"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"


def test_partial_analysis_retry_keeps_successes(client, monkeypatch):
    calls = []
    failing = [True]

    def fake_analyze(self, source, context):
        calls.append(source["prefix"])
        if source["prefix"] == "G2" and failing[0]:
            raise ProviderError("ai_unavailable")
        return summary(source["prefix"])

    def fake_synthesize(self, results, snapshot):
        merged = copy.deepcopy(results[0])
        merged["referensi"] += results[1]["referensi"]
        return merged

    monkeypatch.setattr(VisionProvider, "analyze", fake_analyze)
    monkeypatch.setattr(VisionProvider, "synthesize", fake_synthesize)
    base, board = create_board(client)
    first = upload(client, base, board)
    board["revision"] = first["revision"]
    second = upload(client, base, board, image_bytes("yellow"))
    version = analyze(client, base, board, second["revision"])
    url = f"{base}/{board['id']}/versions/{version['id']}"
    partial = wait_for(client, url)
    assert partial["job_status"] == "partial"
    assert partial["human_summary"]["status_analisis"] == "sebagian_jelas"
    response = client.patch(url + "/review", json={"revision": partial["revision"],
        "decisions": [{"finding_id": f["id"], "decision": "accepted"} for f in partial["findings"]]})
    assert response.status_code == 200
    assert client.post(url + "/approve", json={"revision": 1}).status_code == 409
    failing[0] = False
    response = client.post(f"{base}/{board['id']}/analyses/{version['id']}/retry")
    assert response.status_code == 202
    final = wait_for(client, url)
    assert final["job_status"] == "succeeded"
    assert all(f["review_state"] == "pending" for f in final["findings"])
    assert any(event["event_type"] == "partial_retry" for event in client.get(url + "/events").json()["items"])
    assert calls.count("G1") == 1 and calls.count("G2") == 2


def test_archived_board_is_read_only_but_export_remains_available(client):
    base, board, url, version = completed(client)
    approve_all(client, url, version)
    current = client.get(f"{base}/{board['id']}").json()
    assert client.patch(f"{base}/{board['id']}", json={"revision": current["revision"], "archived": True}).status_code == 200
    assert client.get(base).json()["items"] == []
    assert client.get(base + "?archived=true").json()["total"] == 1
    assert client.post(url + "/exports", json={"language": "id"}, headers={"Idempotency-Key": "archive-export"}).status_code == 201
    assert client.post(f"{base}/{board['id']}/analyses", json={"revision": current["revision"]},
                       headers={"Idempotency-Key": "archived"}).status_code == 409


def test_image_limits_and_low_resolution_warning(monkeypatch):
    monkeypatch.setattr(settings, "moodboard_max_file_bytes", 2)
    with pytest.raises(InvalidImage):
        prepare_image(image_bytes())
    monkeypatch.setattr(settings, "moodboard_max_file_bytes", 1000000)
    metadata, _ = prepare_image(image_bytes(size=(32, 32)))
    assert metadata["warnings"]
    monkeypatch.setattr(settings, "moodboard_max_pixels", 1)
    with pytest.raises(InvalidImage):
        prepare_image(image_bytes())


def test_human_schema_rejects_invented_reference_and_extra_fields():
    value = summary()
    value["gaya_utama"]["referensi"] = ["unknown"]
    with pytest.raises(ValueError):
        HumanSummary.model_validate(value)
    value = summary()
    value["api_key"] = "forbidden"
    with pytest.raises(ValueError):
        HumanSummary.model_validate(value)


def test_http_provider_payload_and_invalid_response(monkeypatch):
    captured = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, headers, json):
            captured.append((url, json))
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = VisionProvider()
    assert provider._request([{"role": "user", "content": "test"}]) == {"ok": True}
    assert captured[0][0].endswith("/chat/completions")
    assert captured[0][1]["response_format"] == {"type": "json_object"}


def test_source_download_is_scoped_and_preview_exists(client):
    base, board = create_board(client)
    result = upload(client, base, board)
    source = result["items"][0]["source"]
    url = f"{base}/{board['id']}/sources/{source['id']}/file"
    assert client.get(url).content == image_bytes()
    assert client.get(url + "?preview=true").headers["content-type"] == "image/jpeg"


def test_rejected_style_and_summary_can_still_acknowledge_unknown(client):
    _, _, url, version = completed(client)
    decisions = [{"finding_id": f["id"], "decision": "rejected" if i < 2 else "accepted"}
                 for i, f in enumerate(version["findings"])]
    result = client.patch(url + "/review", json={"revision": 1, "decisions": decisions})
    assert result.status_code == 200, result.text
    assert result.json()["human_summary"]["gaya_utama"]["deskripsi"] == "unknown"


def test_translation_rejects_changed_color_and_dropped_elements():
    original = summary()
    changed = copy.deepcopy(original)
    changed["palet_warna"][0]["hex_perkiraan"] = "#FFFFFF"
    with pytest.raises(ProviderError):
        validate_translation(original, changed)
    changed = copy.deepcopy(original)
    changed["elemen_visual"]["pencahayaan"] = []
    with pytest.raises(ProviderError):
        validate_translation(original, changed)


def test_patch_source_preserves_notes_and_snapshot(client):
    base, board = create_board(client)
    uploaded = upload(client, base, board)
    source = uploaded["items"][0]["source"]
    source_url = f"{base}/{board['id']}/sources/{source['id']}"
    updated = client.patch(source_url, json={"revision": uploaded["revision"], "notes": "Hanya warna", "roles": ["color"]}).json()
    version = analyze(client, base, board, updated["revision"])
    url = f"{base}/{board['id']}/versions/{version['id']}"
    result = wait_for(client, url)
    excluded = client.patch(source_url, json={"revision": updated["revision"], "included": False})
    assert excluded.status_code == 200
    assert excluded.json()["source"]["notes"] == "Hanya warna"
    assert excluded.json()["source"]["roles"] == ["color"]
    assert result["snapshot"]["sources"][0]["notes"] == "Hanya warna"
    assert client.get(url).json()["snapshot"] == result["snapshot"]


def test_provider_invalid_json_is_retried_once(monkeypatch):
    attempts = []

    def fake(self, messages):
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderError("ai_invalid_output")
        return summary()

    monkeypatch.setattr(VisionProvider, "_request", fake)
    assert VisionProvider()._summary("test")["ringkasan_visual"]
    assert len(attempts) == 2


def test_provider_accepts_fenced_json_and_text_blocks():
    data = summary()
    assert parse_output("```json\n" + json.dumps(data) + "\n```") == data
    assert parse_output([{"type": "text", "text": json.dumps(data)}]) == data
    with pytest.raises(ProviderError):
        parse_output('{"ringkasan_visual":')
    with pytest.raises(ProviderError):
        parse_output('[]')


def test_provider_explicitly_requests_non_streaming(monkeypatch):
    payloads = []

    def post(self, url, **kwargs):
        payloads.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(summary())}, "finish_reason": "stop"}]})

    monkeypatch.setattr(httpx.Client, "post", post)
    assert VisionProvider()._request([{"role": "user", "content": "test"}]) == summary()
    assert payloads[0]["stream"] is False


def test_provider_repair_includes_invalid_output_and_field_errors(monkeypatch, caplog):
    invalid = summary()
    invalid["status_analisis"] = "SECRET_INVALID_VALUE"
    del invalid["elemen_visual"]
    requests = []

    def fake(self, messages):
        requests.append(copy.deepcopy(messages))
        return invalid if len(requests) == 1 else summary()

    monkeypatch.setattr(VisionProvider, "_request", fake)
    assert VisionProvider()._summary("original image evidence") == summary()
    assert requests[1][1]["content"] == "original image evidence"
    assert json.loads(requests[1][-2]["content"]) == invalid
    assert "elemen_visual" in requests[1][-1]["content"]
    assert "literal_error" in requests[1][-1]["content"]
    assert "SECRET_INVALID_VALUE" not in caplog.text


def test_provider_repair_is_bounded_and_preserves_validation_failure(monkeypatch):
    requests = []

    def fake(self, messages):
        requests.append(1)
        return {"ringkasan_visual": "Incomplete"}

    monkeypatch.setattr(VisionProvider, "_request", fake)
    with pytest.raises(ProviderError) as error:
        VisionProvider()._summary("test")
    assert len(requests) == 2
    assert error.value.details and error.value.code == "ai_invalid_output"


def test_cancelled_job_never_publishes_late_results(client, monkeypatch):
    from threading import Event
    entered, release = Event(), Event()

    def blocking(self, source, context):
        entered.set()
        assert release.wait(5)
        return summary(source["prefix"])

    monkeypatch.setattr(VisionProvider, "analyze", blocking)
    base, board = create_board(client)
    result = upload(client, base, board)
    version = analyze(client, base, board, result["revision"])
    try:
        assert entered.wait(5)
        response = client.post(f"{base}/{board['id']}/analyses/{version['id']}/cancel")
        assert response.status_code == 200
    finally:
        release.set()
    client.app.state.moodboard_runner.close()
    result = client.get(f"{base}/{board['id']}/versions/{version['id']}").json()
    assert result["job_status"] == "cancelled" and result["human_summary"] is None
