import base64
import io
import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.modules.shots.model import ShotImage
from app.modules.shots.image_provider import extract_image
from app.modules.shots.image_provider import ImageProvider
import httpx
from app.core.ai_provider import ProviderError
from tests.conftest import TestSession


def setup_shot(client, approved=True):
    pid = client.post('/projects', json={'name': 'Image workflow'}).json()['id']
    shot = client.post(f'/projects/{pid}/shots', json={'title': 'Warm living room'}).json()
    url = f'/projects/{pid}/shots/{shot["id"]}/revisions'
    history = client.get(url).json()
    revision_id = history['active_revision_id']
    if approved:
        assert client.post(f'{url}/{revision_id}/review', json={'decision': 'approve', 'expected_active_id': revision_id}).status_code == 200
    return pid, shot['id'], revision_id


@pytest.fixture
def image_queue(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'ai_api_key', 'test-key')
    monkeypatch.setattr(settings, 'ai_image_api_mode', 'chat')
    monkeypatch.setattr(settings, 'shot_image_storage_dir', str(tmp_path))
    jobs = []
    runner = client.app.state.shot_image_runner
    monkeypatch.setattr(runner, 'submit', lambda *args: jobs.append(args))
    output = io.BytesIO()
    Image.new('RGB', (256, 256), 'green').save(output, 'PNG')
    monkeypatch.setattr(runner.provider, 'generate', lambda *args: output.getvalue())
    return jobs, runner


def test_queue_approval_dedup_and_real_file(client, image_queue):
    jobs, runner = image_queue
    pid, shot_id, revision_id = setup_shot(client)
    endpoint = f'/projects/{pid}/shot-images'
    payload = {'shot_id': shot_id, 'revision_id': revision_id}
    assert client.post(endpoint + '/generate', json=payload).status_code == 202
    assert client.post(endpoint + '/generate', json=payload).status_code == 202
    assert len(jobs) == 1
    runner.run(*jobs[0])
    result = client.get(endpoint).json()['items'][0]
    assert result['status'] == 'succeeded'
    response = client.get(result['url'])
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    assert response.content.startswith(b'\x89PNG')
    client.post(endpoint + '/generate', json=payload)
    assert len(jobs) == 1
    other, _, _ = setup_shot(client)
    assert client.get(result['url'].replace(pid, other)).status_code == 404


def test_unapproved_blocked_and_batch_only_approved(client, image_queue):
    jobs, _ = image_queue
    pid, shot_id, revision_id = setup_shot(client, False)
    assert client.post(f'/projects/{pid}/shot-images/generate', json={'shot_id': shot_id, 'revision_id': revision_id}).status_code == 409
    assert client.post(f'/projects/{pid}/shot-images/generate-approved').json()['queued'] == 0
    assert jobs == []
    client.post(f'/projects/{pid}/shots/{shot_id}/revisions/{revision_id}/review', json={'decision': 'approve', 'expected_active_id': revision_id})
    client.post(f'/projects/{pid}/shots', json={'title': 'Unapproved extra'})
    result = client.post(f'/projects/{pid}/shot-images/generate-approved').json()
    assert result['queued'] == 1 and len(result['items']) == 1


def test_stale_job_never_publishes_image(client, image_queue, monkeypatch):
    jobs, runner = image_queue
    pid, shot_id, revision_id = setup_shot(client)
    client.post(f'/projects/{pid}/shot-images/generate', json={'shot_id': shot_id, 'revision_id': revision_id})
    def generate(*args):
        url = f'/projects/{pid}/shots/{shot_id}/revisions'
        row = client.post(url, json={'parent_id': revision_id, 'change_note': 'New framing'}).json()['items'][-1]
        client.post(f'{url}/{row["id"]}/review', json={'decision': 'approve', 'expected_active_id': revision_id})
        output = io.BytesIO()
        Image.new('RGB', (256, 256)).save(output, 'PNG')
        return output.getvalue()
    monkeypatch.setattr(runner.provider, 'generate', generate)
    runner.run(*jobs[0])
    result = client.get(f'/projects/{pid}/shot-images').json()['items'][0]
    assert result['status'] == 'stale' and result['url'] is None


def test_provider_failure_can_be_retried(client, image_queue, monkeypatch):
    jobs, runner = image_queue
    pid, shot_id, revision_id = setup_shot(client)
    endpoint = f'/projects/{pid}/shot-images/generate'
    payload = {'shot_id': shot_id, 'revision_id': revision_id}
    client.post(endpoint, json=payload)
    def failure(*args):
        raise ProviderError('image_output_missing')
    monkeypatch.setattr(runner.provider, 'generate', failure)
    runner.run(*jobs[0])
    assert client.get(f'/projects/{pid}/shot-images').json()['items'][0]['error_code'] == 'image_output_missing'
    assert client.post(endpoint, json=payload).json()['status'] == 'queued'
    assert len(jobs) == 2 and jobs[0][1] != jobs[1][1]


def test_parser_accepts_images_but_rejects_text_only():
    encoded = base64.b64encode(b'example').decode()
    assert extract_image({'choices': [{'message': {'images': [{'image_url': {'url': 'data:image/png;base64,' + encoded}}]}}]}) == b'example'
    assert extract_image({'data': [{'b64_json': encoded}]}) == b'example'
    with pytest.raises(ProviderError, match='image_output_missing'):
        extract_image({'choices': [{'message': {'content': 'Here is a description of an image.'}}]})


def test_provider_reports_upstream_tool_failure_without_claiming_success(monkeypatch):
    monkeypatch.setattr(settings, 'ai_api_key', 'test-key')
    monkeypatch.setattr(settings, 'ai_image_api_mode', 'chat')
    real_client = httpx.Client
    def respond(request):
        assert request.url.path.endswith('/chat/completions')
        return httpx.Response(200, json={'model': 'gemini-3.8-flash-n', 'choices': [{'finish_reason': 'malformed_function_call', 'message': {'role': 'assistant', 'content': ''}}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(ProviderError) as error:
        ImageProvider().generate('Approved shot', {'moodboards': []})
    assert error.value.code == 'image_provider_tool_error'
    assert error.value.details['model'] == 'gemini-3.8-flash-n'


def test_provider_extracts_actual_chat_image_output(monkeypatch):
    monkeypatch.setattr(settings, 'ai_api_key', 'test-key')
    monkeypatch.setattr(settings, 'ai_image_api_mode', 'chat')
    real_client = httpx.Client
    image = base64.b64encode(b'image-bytes').decode()
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + image}}]}}]})), **kwargs))
    assert ImageProvider().generate('Approved shot', {'moodboards': []}) == b'image-bytes'


def test_gemini_native_uses_separate_key_and_reference_images(monkeypatch, tmp_path):
    import json
    import app.modules.shots.image_provider as provider_module
    monkeypatch.setattr(settings, 'ai_image_api_mode', 'gemini')
    monkeypatch.setattr(settings, 'ai_image_model', 'gemini-3.1-flash-image')
    monkeypatch.setattr(settings, 'gemini_api_key', 'google-test-key')
    monkeypatch.setattr(settings, 'ai_api_key', '')
    reference = tmp_path / 'reference.jpg'
    reference.write_bytes(b'reference-image')
    monkeypatch.setattr(provider_module, 'storage_path', lambda key: reference)
    real_client = httpx.Client
    def respond(request):
        assert str(request.url) == 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image:generateContent'
        assert request.headers['x-goog-api-key'] == 'google-test-key'
        assert 'authorization' not in request.headers
        payload = json.loads(request.content)
        assert payload['generationConfig']['responseModalities'] == ['TEXT', 'IMAGE']
        assert base64.b64decode(payload['contents'][0]['parts'][1]['inlineData']['data']) == b'reference-image'
        return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'Done'}, {'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(b'generated-image').decode()}}]}}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    assert ImageProvider().generate('Approved shot', {'moodboards': [], 'reference_keys': ['reference.jpg']}) == b'generated-image'


def test_missing_gemini_key_fails_before_queue_and_config_never_exposes_keys(client, image_queue, monkeypatch):
    jobs, _ = image_queue
    monkeypatch.setattr(settings, 'ai_image_api_mode', 'gemini')
    monkeypatch.setattr(settings, 'gemini_api_key', '')
    pid, shot_id, revision_id = setup_shot(client)
    response = client.post(f'/projects/{pid}/shot-images/generate', json={'shot_id': shot_id, 'revision_id': revision_id})
    assert response.status_code == 503 and 'GEMINI_API_KEY' in response.json()['error']['message']
    assert jobs == []
    config = client.get(f'/projects/{pid}/shot-images/config').json()
    assert config['configured'] is False and config['missing_key'] == 'GEMINI_API_KEY'
    assert 'test-key' not in json_string(config)


def json_string(value):
    import json
    return json.dumps(value)


def test_gemini_safety_block_is_reported(monkeypatch):
    monkeypatch.setattr(settings, 'ai_image_api_mode', 'gemini')
    monkeypatch.setattr(settings, 'gemini_api_key', 'google-test-key')
    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'promptFeedback': {'blockReason': 'SAFETY'}})), **kwargs))
    with pytest.raises(ProviderError) as error:
        ImageProvider().generate('Approved shot', {})
    assert error.value.code == 'image_provider_blocked'
