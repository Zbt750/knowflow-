from uuid import uuid4
from fastapi.testclient import TestClient
from tests.integration.test_generation_confirmation_recovery import generation_fixture, application, events, setup_confirmation


def test_changed_location_expires_card_durably_and_new_request_can_reconfirm(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    with TestClient(application(factory, model)) as client:
        payload, old_id = setup_confirmation(client, sid, kp)
        changed = {**payload, "study_context":{"surface":"study", "knowledge_node_ids":[]}}
        rejected = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream', json=changed))
        assert rejected[-1][1]['code'] == 'personal_generation_confirmation_invalid'
        assert model.calls == 0
        for _ in range(2):
            history = client.get(f'/api/chat/sessions/{sid}/messages').json()
            old = next(row for row in history if row['message_id'] == old_id)
            assert old['personal_generation_confirmation'] is None
            assert old['personal_generation_confirmation_status'] == 'expired'
        original = {"question":payload['question'],"request_key":str(uuid4()),"study_context":changed['study_context']}
        fresh = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream', json=original))
        assert any(name == 'personal_generation_confirmation' for name, _ in fresh)
        new_id = next(data['message_id'] for name, data in fresh if name == 'meta')
        assert new_id != old_id
        confirmed = {**original, "request_key":str(uuid4()),
            "personal_generation_confirmation_message_id":new_id,"personal_generation_confirmed_kp_id":str(kp)}
        generated = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream', json=confirmed))
        assert any(name == 'personal_generation' and len(data['question_ids']) == 1 for name, data in generated)
        events(client.post(f'/api/chat/sessions/{sid}/assistant:stream', json=confirmed))
        assert model.calls == 1
