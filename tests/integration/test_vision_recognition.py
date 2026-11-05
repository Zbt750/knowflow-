from uuid import UUID, uuid4
import httpx
import pytest
from sqlalchemy import func, select

from backend.api.routes import study as routes
from backend.models.learning import LearningEvent, QuestionAttempt, PracticeItem
from backend.services.vision_recognition_service import RecognitionResponse
from backend.services import vision_recognition_service as vision
from tests.unit.test_vision import image_bytes
from tests.unit.test_model_settings import settings
from tests.integration.test_process_reviews import calculation_item
from tests.integration.test_learning_loop import client, clock, clean_database, session_factory


def upload(client, item, consent='true'):
    return client.post(f'/api/practice-items/{item}/recognize-work', data={'consent':consent},
                       files={'file':('process.png',b'synthetic-mocked-image','image/png')})


def test_recognition_returns_confirmable_text_without_learning_writes(client, calculation_item, session_factory, monkeypatch):
    async def recognize(settings, data):
        assert data == b'synthetic-mocked-image'
        return RecognitionResponse(text='原始过程，待用户修改确认。',model='synthetic-vision',duration_ms=1)
    monkeypatch.setattr(routes,'recognize_work',recognize)
    result = upload(client,calculation_item)
    assert result.status_code == 200, result.text
    assert result.json()['requires_confirmation'] and not result.json()['changes_mastery']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 0
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0
        assert db.get(PracticeItem,UUID(calculation_item)).completed_at is None


def test_recognition_no_consent_or_missing_item_never_calls_provider(client, calculation_item, monkeypatch):
    async def forbidden(*args): raise AssertionError('unexpected model request')
    monkeypatch.setattr(routes,'recognize_work',forbidden)
    assert upload(client,calculation_item,'false').status_code == 403
    assert upload(client,str(uuid4())).status_code == 404


def test_recognition_missing_file_and_bad_uuid_use_error_envelope(client):
    response = client.post('/api/practice-items/not-uuid/recognize-work',data={'consent':'true'})
    assert response.status_code == 422 and response.json()['error']['code'] == 'validation_failed'


def test_cross_site_image_request_rejected_before_model(client, calculation_item, monkeypatch):
    async def forbidden(*args): raise AssertionError('unexpected cross-site model request')
    monkeypatch.setattr(routes, 'recognize_work', forbidden)
    result = client.post(f'/api/practice-items/{calculation_item}/recognize-work',
                        headers={'Origin':'https://evil.example','Sec-Fetch-Site':'cross-site'},
                        data={'consent':'true'}, files={'file':('process.png', b'synthetic', 'image/png')})
    assert result.status_code == 403


@pytest.mark.parametrize('choice', [None, 123, 'invalid'])
def test_malformed_provider_choice_returns_controlled_route_error(
    client, calculation_item, session_factory, monkeypatch, tmp_path, choice,
):
    calls = []
    original = httpx.AsyncClient
    def respond(request):
        calls.append(1)
        return httpx.Response(200, json={'choices': [choice]})
    monkeypatch.setattr(vision.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(vision, 'effective_vision_settings', lambda _: settings(tmp_path))
    response = client.post(f'/api/practice-items/{calculation_item}/recognize-work',
                           data={'consent': 'true'}, files={'file': ('process.png', image_bytes(), 'image/png')})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'vision_output_incomplete'
    assert len(calls) == 1 and 'original-test-key' not in response.text
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 0
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0
