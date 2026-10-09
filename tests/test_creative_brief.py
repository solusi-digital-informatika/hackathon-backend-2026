import pytest
from sqlalchemy import func, select
from app.core.ai_provider import ProviderError
from app.modules.brief.creative import CreativeResult, CreativeSections
from app.modules.brief.model import SourceDocument, ProjectBrief
from tests.conftest import TestSession


def output(count=0, relevance="creative_brief"):
    return CreativeResult.model_validate({
        "relevance": relevance, "reason": "Resep ini tidak memuat tujuan produksi kreatif." if relevance == "irrelevant" else "Brief kampanye",
        "sections": {key: "Belum ditentukan" for key in CreativeSections.model_fields} if relevance != "irrelevant" else None,
        "objective": "Kampanye FitLife", "visual_style": "Cinematic", "lighting_mood": "Cerah",
        "characters": [], "key_props": [], "constraints": [], "unresolved_questions": ["Berapa anggaran?"],
        "storyboard": [{"title": f"Scene {i + 1}", "description": "Model melihat aplikasi FitLife, framing medium, transisi cut."} for i in range(count)] if relevance != "irrelevant" else [],
    })


def project(client):
    return client.post('/projects', json={"name": "AI brief test"}).json()['id']


def test_brief_waits_for_explicit_shot_generation_and_preserves_versions(client, monkeypatch):
    monkeypatch.setattr('app.modules.brief.router.generate', lambda data: output())
    pid = project(client)
    payload = {"source_name": "FitLife", "content": "Buat iklan FitLife"}
    first = client.post(f'/projects/{pid}/brief/generate', json=payload)
    assert first.status_code == 201
    brief = first.json()['brief']
    assert brief['version'] == 1
    assert len(brief['creative_sections']) == 8
    assert brief['storyboard'] == brief['generated_shot_ids'] == []
    assert client.get(f'/projects/{pid}/shots').json()['total'] == 0
    from app.modules.brief.storyboard import StoryboardResult
    def storyboard(*args):
        return StoryboardResult(shots=[dict(title=f'Scene {i}', description='Action', action='Run', framing='Wide', camera_movement='Pan', lighting='Warm', environment='Home', subjects='Actor', transition='Cut', image_prompt='Actor running at home') for i in range(args[-1])])
    monkeypatch.setattr('app.modules.brief.router.generate_storyboard', storyboard)
    generated = client.post(f'/projects/{pid}/brief/storyboard', json={'brief_id': brief['id']})
    assert generated.status_code == 200
    assert len(generated.json()['generated_shot_ids']) == 7
    again = client.post(f'/projects/{pid}/brief/storyboard', json={'brief_id': brief['id']})
    assert again.json()['generated_shot_ids'] == generated.json()['generated_shot_ids']
    assert client.get(f'/projects/{pid}/shots').json()['items'][0]['generation_details']['image_prompt']
    assert brief['review_status'] == 'pending_review'
    assert client.get(f'/projects/{pid}/brief').json()['brief']['id'] == brief['id']
    second = client.post(f'/projects/{pid}/brief/generate', json={**payload, "shot_count": 3})
    assert second.status_code == 201
    assert second.json()['brief']['version'] == 2
    assert client.get(f'/projects/{pid}/shots').json()['total'] == 7
    second_shots = client.post(f'/projects/{pid}/brief/storyboard', json={'brief_id': second.json()['brief']['id'], 'shot_count': 3})
    assert second_shots.status_code == 200
    shots = client.get(f'/projects/{pid}/shots').json()['items']
    assert len(shots) == 10 and all(s['status'] == 'draft' for s in shots)
    with TestSession() as db:
        assert db.get(ProjectBrief, brief['id']) is not None
    edited = dict(second.json()['brief']['creative_sections'], core_message='Pesan yang dikoreksi manusia')
    updated = client.put(f'/projects/{pid}/brief', json={"creative_sections": edited})
    assert updated.status_code == 200
    assert updated.json()['creative_sections']['core_message'] == 'Pesan yang dikoreksi manusia'
    assert updated.json()['version'] == 2


@pytest.mark.parametrize('failure', ['irrelevant', 'unavailable'])
def test_rejected_or_failed_ai_does_not_save_source_brief_or_shots(client, monkeypatch, failure):
    def fake(data):
        if failure == 'unavailable':
            raise ProviderError('ai_unavailable')
        return output(relevance='irrelevant')
    monkeypatch.setattr('app.modules.brief.router.generate', fake)
    pid = project(client)
    response = client.post(f'/projects/{pid}/brief/generate', json={"source_name": "Recipe", "content": "Rebus telur"})
    assert response.status_code == (422 if failure == 'irrelevant' else 503)
    with TestSession() as db:
        assert db.scalar(select(func.count()).select_from(SourceDocument).where(SourceDocument.project_id == pid)) == 0
        assert db.scalar(select(func.count()).select_from(ProjectBrief).where(ProjectBrief.project_id == pid)) == 0
    assert client.get(f'/projects/{pid}/shots').json()['total'] == 0


@pytest.mark.parametrize('count', [0, 31, 1.5, '7'])
def test_invalid_shot_count_never_calls_ai(client, monkeypatch, count):
    def fail(data):
        pytest.fail('AI should not run for invalid input')
    monkeypatch.setattr('app.modules.brief.router.generate', fail)
    pid = project(client)
    assert client.post(f'/projects/{pid}/brief/storyboard', json={"brief_id": "brief_invalid", "shot_count": count}).status_code == 400


def test_ai_cannot_generate_shots_during_brief_input(monkeypatch):
    from app.modules.brief.creative import generate, GenerateRequest
    calls = []
    def wrong(self, messages):
        calls.append(messages.copy())
        return output(2).model_dump()
    monkeypatch.setattr('app.core.ai_provider.ChatProvider._request', wrong)
    with pytest.raises(ProviderError, match='ai_invalid_output'):
        generate(GenerateRequest(source_name='Brief', content='Buat video kampanye'))
    assert len(calls) == 2
