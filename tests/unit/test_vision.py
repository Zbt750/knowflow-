import base64
from io import BytesIO
import json
import os

import httpx
from PIL import Image
import pytest

from backend.errors import AppError
from backend.services import vision_recognition_service as vision
from backend.services.vision_settings_service import (
    VisionSettingsUpdate, effective_vision_settings, load_vision_settings,
    save_vision_settings, settings_path,
)
from tests.unit.test_model_settings import settings, client_for


def image_bytes(format="PNG"):
    output = BytesIO()
    image = Image.new("RGB", (8, 8), "white")
    image.save(output, format=format)
    return output.getvalue()


def test_default_reuses_chat_without_copying_or_exposing_key(tmp_path):
    value = settings(tmp_path)
    assert effective_vision_settings(value).llm_api_key.get_secret_value() == "original-test-key"
    with client_for(value) as client:
        view = client.get('/api/settings/vision')
        assert view.status_code == 200 and view.json()['reuse_chat_model']
        assert not view.json()['key_configured'] and view.json()['configured']
        assert 'original-test-key' not in view.text
    assert not settings_path(value).exists()


def test_independent_key_preserve_clear_restart_does_not_change_chat(tmp_path):
    value = settings(tmp_path)
    with client_for(value) as client:
        token = client.get('/api/settings/vision').json()['csrf_token']
        body = dict(base_url='https://example.com/v1', model='vision-only', reuse_chat_model=False, api_key='synthetic-vision-key')
        result = client.put('/api/settings/vision', json=body, headers={'X-Settings-Token':token})
        assert result.status_code == 200 and 'synthetic-vision-key' not in result.text
        assert effective_vision_settings(value).llm_model == 'vision-only'
        assert value.llm_model == 'old-model' and not value.model_settings_path.exists()
        del body['api_key']
        assert client.put('/api/settings/vision', json=body, headers={'X-Settings-Token':token}).status_code == 200
        assert load_vision_settings(value)[0].api_key.get_secret_value() == 'synthetic-vision-key'
        if os.name == 'nt':
            assert b'synthetic-vision-key' not in settings_path(value).read_bytes()
        body['clear_key'] = True
        assert client.put('/api/settings/vision', json=body, headers={'X-Settings-Token':token}).status_code == 200
        with pytest.raises(AppError) as error:
            effective_vision_settings(value)
        assert error.value.code == 'vision_not_configured'


@pytest.mark.parametrize('headers', [{}, {'X-Settings-Token':'wrong'}, {'Origin':'https://evil.example'}])
def test_vision_write_requires_local_csrf(tmp_path, headers):
    value = settings(tmp_path)
    with client_for(value) as client:
        client.get('/api/settings/vision')
        result = client.put('/api/settings/vision', json={'base_url':'https://example.com','model':'vision'}, headers=headers)
        assert result.status_code == 403
    assert not settings_path(value).exists()


def test_damaged_vision_config_does_not_fallback_to_chat_key(tmp_path):
    value = settings(tmp_path)
    path = settings_path(value); path.parent.mkdir(); path.write_bytes(b'damaged')
    with pytest.raises(AppError) as error: effective_vision_settings(value)
    assert error.value.code == 'vision_not_configured'


@pytest.mark.parametrize('data', [b'', b'not an image', b'a'*(vision.MAX_IMAGE_BYTES+1), image_bytes('GIF')],
                         ids=['empty', 'invalid-content', 'oversized', 'gif-not-supported'])
def test_image_validation_rejects_invalid_content(data):
    with pytest.raises(AppError) as error: vision.normalized_image(data)
    assert error.value.code == 'vision_image_invalid'


def test_image_reencode_strips_metadata_and_handles_alpha():
    from PIL.PngImagePlugin import PngInfo
    metadata = PngInfo(); metadata.add_text('private-location','synthetic-location')
    output = BytesIO(); Image.new('RGBA',(8,8),(0,0,0,0)).save(output,format='PNG',pnginfo=metadata)
    cleaned = vision.normalized_image(output.getvalue())
    assert b'synthetic-location' not in cleaned
    with Image.open(BytesIO(cleaned)) as image:
        assert image.mode == 'RGB' and image.getpixel((0,0)) == (255,255,255)


@pytest.mark.asyncio
async def test_multimodal_payload_usage_and_no_persistence(tmp_path, monkeypatch):
    calls = []
    original = httpx.AsyncClient
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'学生过程：[无法辨认]，然后积分。'},'finish_reason':'stop'}],
                                        'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
    monkeypatch.setattr(vision.httpx,'AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(respond)))
    result = await vision.recognize_work(settings(tmp_path), image_bytes())
    assert result.requires_confirmation and not result.changes_mastery and not result.image_stored
    assert result.usage['total_tokens'] == 15 and len(calls) == 1
    blocks = calls[0]['messages'][1]['content']
    assert '伪代码必须保留原始符号与缩进' in calls[0]['messages'][0]['content']
    assert blocks[1]['type'] == 'image_url'
    data_url = blocks[1]['image_url']['url']
    assert data_url.startswith('data:image/png;base64,')
    assert base64.b64decode(data_url.split(',',1)[1]).startswith(b'\x89PNG')
    assert not list(tmp_path.rglob('*'))


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', [
    {'message':{'content':'partial'},'finish_reason':'length'},
    {'message':{'content':''},'finish_reason':'stop'},
    {'message':{'content':'a'*4001},'finish_reason':'stop'},
    {'message':{'content':'refused'},'finish_reason':'content_filter'},
    {'message':{'content':'partial'}},
], ids=['truncated', 'empty', 'overlong', 'filtered', 'missing-finish-reason'])
async def test_incomplete_output_not_retried_or_silently_cut(tmp_path, monkeypatch, choice):
    count = []
    original = httpx.AsyncClient
    def respond(request):
        count.append(1); return httpx.Response(200,json={'choices':[choice]})
    monkeypatch.setattr(vision.httpx,'AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(respond)))
    with pytest.raises(AppError) as error: await vision.recognize_work(settings(tmp_path),image_bytes())
    assert error.value.code == 'vision_output_incomplete' and len(count) == 1


@pytest.mark.asyncio
async def test_admission_is_bounded_and_released_after_invalid_image(tmp_path):
    with pytest.raises(AppError): await vision.recognize_work(settings(tmp_path), b'bad')
    assert vision._SLOTS.acquire(blocking=False) and vision._SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(AppError) as error: await vision.recognize_work(settings(tmp_path),image_bytes())
        assert error.value.code == 'vision_busy'
    finally:
        vision._SLOTS.release(); vision._SLOTS.release()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', 'unauthorized', 'malformed-json'])
async def test_upstream_failure_is_safe_single_call_and_releases_slot(tmp_path, monkeypatch, failure):
    calls = []
    original = httpx.AsyncClient
    def respond(request):
        calls.append(1)
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic-private-detail', request=request)
        if failure == 'unauthorized':
            return httpx.Response(401, text='synthetic-private-detail')
        return httpx.Response(200, text='not-json synthetic-private-detail')
    monkeypatch.setattr(vision.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond)))
    with pytest.raises(AppError) as error:
        await vision.recognize_work(settings(tmp_path), image_bytes())
    assert len(calls) == 1
    assert 'synthetic-private-detail' not in json.dumps(error.value.to_payload())
    assert vision._SLOTS.acquire(blocking=False) and vision._SLOTS.acquire(blocking=False)
    vision._SLOTS.release(); vision._SLOTS.release()


def test_large_dimensions_rejected_before_decode():
    output = BytesIO()
    Image.new('RGB', (4097, 1), 'white').save(output, format='PNG')
    with pytest.raises(AppError) as error:
        vision.normalized_image(output.getvalue())
    assert error.value.code == 'vision_image_invalid'
