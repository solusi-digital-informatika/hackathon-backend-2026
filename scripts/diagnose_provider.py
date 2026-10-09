"""Print response shape only; never print credentials, prompts, or generated content."""
import json
import httpx
import base64
import sys
from app.core.config import settings

messages = [{'role': 'user', 'content': 'Return only JSON: {"ok": true}'}]
if len(sys.argv) > 1:
    from app.core.database import SessionLocal
    from app.modules.moodboards.model import ExtractionVersion
    from app.modules.moodboards.provider import SYSTEM
    from app.modules.moodboards.schemas import HumanSummary
    from app.modules.moodboards.storage import storage_path
    with SessionLocal() as db:
        version = db.get(ExtractionVersion, sys.argv[1])
        source = version.snapshot['sources'][0]
        image = base64.b64encode(storage_path(source['analysis_key']).read_bytes()).decode()
        metadata = {k: source[k] for k in ('prefix', 'label', 'notes', 'roles', 'warnings')}
        messages = [{'role': 'system', 'content': SYSTEM + '\nJSON schema:\n' + json.dumps(HumanSummary.model_json_schema())},
                    {'role': 'user', 'content': [{'type': 'text', 'text': json.dumps({'source': metadata, 'context': version.snapshot['context']})},
                     {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + image}}]}]
response = httpx.post(settings.ai_base_url.rstrip('/') + '/chat/completions',
    headers={'Authorization': 'Bearer ' + settings.ai_api_key},
    json={'model': settings.ai_vision_model,
          'messages': messages,
          'response_format': {'type': 'json_object'}, 'temperature': 0.2, 'stream': False},
    timeout=settings.ai_timeout_seconds)
result = {'status': response.status_code, 'content_type': response.headers.get('content-type'),
          'response_bytes': len(response.content), 'looks_like_sse': response.text.lstrip().startswith('data:')}
try:
    body = response.json()
    result['json_type'] = type(body).__name__
    if isinstance(body, dict):
        result['top_level_keys'] = list(body)
        choices = body.get('choices')
        result['choices_type'] = type(choices).__name__
        if isinstance(choices, list) and choices:
            result['choice_keys'] = list(choices[0])
            message = choices[0].get('message', {})
            result['message_keys'] = list(message)
            result['content_type_in_message'] = type(message.get('content')).__name__
except ValueError:
    result['json_parse_failed'] = True
print(json.dumps(result))
