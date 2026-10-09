import pytest
from app.core.ai_provider import ChatProvider, ProviderError


def setup(client):
    pid = client.post('/projects', json={'name': 'Revision workflow'}).json()['id']
    shot = client.post(f'/projects/{pid}/shots', json={'title': 'Original', 'description': 'Original description'}).json()
    url = f'/projects/{pid}/shots/{shot["id"]}'
    history = client.get(url + '/revisions').json()
    return url, history


def branch(client, url, parent, title='New proposal'):
    response = client.post(url + '/revisions', json={'parent_id': parent, 'title': title, 'description': 'Revised description', 'change_note': 'Make lighting warmer'})
    assert response.status_code == 201
    return response.json()


def test_branch_increment_preserves_original_until_human_merge(client):
    url, history = setup(client)
    original = history['active_revision_id']
    proposed = branch(client, url, original)
    assert [r['version_number'] for r in proposed['items']] == [1, 2]
    revision = proposed['items'][-1]
    assert revision['parent_id'] == original and revision['status'] == 'pending_review'
    assert client.get(url).json()['title'] == 'Original'
    assert client.get(url).json()['revision_summary']['pending'] == 1
    merged = client.post(url + f'/revisions/{revision["id"]}/review', json={'decision': 'approve', 'expected_active_id': original, 'note': 'Approved by creative lead'})
    assert merged.status_code == 200
    assert merged.json()['active_revision_id'] == revision['id']
    assert client.get(url).json()['title'] == 'New proposal'
    assert client.get(url).json()['status'] == 'approved'
    assert merged.json()['items'][0]['description'] == 'Original description'
    assert merged.json()['items'][-1]['reviewed_at']
    assert client.patch(url, json={'title': 'Overwrite'}).status_code == 409
    assert client.delete(url).status_code == 409


def test_parallel_branches_keep_global_increment_and_conflicting_merge_is_blocked(client):
    url, history = setup(client)
    root = history['active_revision_id']
    second = branch(client, url, root)['items'][-1]
    third = branch(client, url, root, 'Alternative')['items'][-1]
    assert third['version_number'] == 3 and third['parent_id'] == root
    assert client.post(url + f'/revisions/{second["id"]}/review', json={'decision': 'approve', 'expected_active_id': root}).status_code == 200
    stale = client.post(url + f'/revisions/{third["id"]}/review', json={'decision': 'approve', 'expected_active_id': second['id']})
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'branch_conflict'
    rejected = client.post(url + f'/revisions/{third["id"]}/review', json={'decision': 'reject', 'expected_active_id': second['id'], 'note': 'Keep merged version'})
    assert rejected.status_code == 200
    assert rejected.json()['items'][-1]['status'] == 'rejected'
    assert rejected.json()['active_revision_id'] == second['id']


def test_ai_regeneration_creates_branch_without_changing_shot(client, monkeypatch):
    url, history = setup(client)
    monkeypatch.setattr(ChatProvider, '_request', lambda *a, **k: dict(title='AI proposal', description='New camera angle', action='Run', framing='Wide', camera_movement='Pan', lighting='Warm', environment='Home', subjects='Model', transition='Cut', image_prompt='Warm home scene'))
    response = client.post(url + '/revisions', json={'parent_id': history['active_revision_id'], 'mode': 'ai', 'change_note': 'Warm lighting'})
    assert response.status_code == 201
    assert response.json()['items'][-1]['details']['image_prompt'] == 'Warm home scene'
    assert client.get(url).json()['title'] == 'Original'


def test_ai_failure_preserves_history(client, monkeypatch):
    url, history = setup(client)
    def failure(*args):
        raise ProviderError('ai_unavailable')
    monkeypatch.setattr(ChatProvider, '_request', failure)
    assert client.post(url + '/revisions', json={'parent_id': history['active_revision_id'], 'mode': 'ai', 'change_note': 'Warm'}).status_code == 502
    assert len(client.get(url + '/revisions').json()['items']) == 1


def test_cannot_branch_from_another_shot_or_merge_with_stale_active_id(client):
    url, history = setup(client)
    other_url, other = setup(client)
    assert client.post(url + '/revisions', json={'parent_id': other['active_revision_id'], 'change_note': 'Invalid parent'}).status_code == 404
    row = branch(client, url, history['active_revision_id'])['items'][-1]
    assert client.post(url + f'/revisions/{row["id"]}/review', json={'decision': 'approve', 'expected_active_id': 'stale'}).status_code == 409


def test_images_require_current_approved_version(client):
    url, history = setup(client)
    root = history['active_revision_id']
    def eligible(revision):
        return client.get(url + f'/revisions/{revision}/image-eligibility')
    assert eligible(root).status_code == 409
    approved = client.post(url + f'/revisions/{root}/review', json={'decision': 'approve', 'expected_active_id': root})
    assert approved.status_code == 200
    assert approved.json()['items'][0]['can_generate_image'] is True
    assert eligible(root).status_code == 200
    pending = branch(client, url, root)['items'][-1]
    assert eligible(pending['id']).status_code == 409
    assert eligible(root).status_code == 200
    client.post(url + f'/revisions/{pending["id"]}/review', json={'decision': 'reject', 'expected_active_id': root})
    assert eligible(pending['id']).status_code == 409
    next_version = branch(client, url, root)['items'][-1]
    client.post(url + f'/revisions/{next_version["id"]}/review', json={'decision': 'approve', 'expected_active_id': root})
    assert eligible(next_version['id']).status_code == 200
    assert eligible(root).status_code == 409
    other_url, other = setup(client)
    assert eligible(other['active_revision_id']).status_code == 404
