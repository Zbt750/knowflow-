"""Purpose is a server-side boundary, not a title-based frontend filter."""
from uuid import uuid4
from fastapi.testclient import TestClient
from tests.integration.test_generation_confirmation_recovery import generation_fixture,application,events


def test_study_and_qa_history_cards_replay_and_crud_are_separate(generation_fixture):
    factory,_,kp,_,model = generation_fixture
    with TestClient(application(factory,model)) as client:
        study = client.post('/api/chat/sessions',json={'title':'今日学习','mode':'builtin','purpose':'study'}).json()
        qa = client.post('/api/chat/sessions',json={'title':'独立深入讨论','mode':'builtin','purpose':'qa'}).json()
        def submit(session,surface):
            body={'question':'请新编一道类似的新题，但是要更难一点。原题：当|x|<1时，求级数sum nx^n的和。',
                'request_key':str(uuid4()),'study_context':{'surface':surface,'knowledge_node_ids':[str(kp)]}}
            response=events(client.post(f'/api/chat/sessions/{session["session_id"]}/assistant:stream',json=body,params={'purpose':'study' if surface=='study' else 'qa'}))
            assert any(name=='personal_generation_confirmation' for name,_ in response),response
            return body,next(data['message_id'] for name,data in response if name=='meta')
        study_body,card=submit(study,'study')
        qa_body,_=submit(qa,'chat')
        study_id,qa_id=study['session_id'],qa['session_id']
        assert study_id != qa_id
        listing=client.get('/api/chat/sessions?mode=builtin&purpose=qa').json()
        assert qa_id in {s['session_id'] for s in listing}
        assert study_id not in {s['session_id'] for s in listing}
        assert study_id not in {s['session_id'] for s in client.get('/api/chat/sessions').json()}
        own=client.get('/api/chat/sessions?mode=builtin&purpose=study').json()
        assert any(s['session_id']==study_id and s['study_date'] for s in own)
        before=client.get(f'/api/chat/sessions/{study_id}/messages',params={'purpose':'study'}).json()
        replay=events(client.post(f'/api/chat/sessions/{study_id}/assistant:stream',json=study_body,params={'purpose':'study'}))
        assert any(name=='meta' and data.get('replayed') for name,data in replay)
        assert client.get(f'/api/chat/sessions/{study_id}/messages',params={'purpose':'study'}).json()==before
        bad={**qa_body,'request_key':str(uuid4()),'personal_generation_confirmed_kp_id':str(kp),
             'personal_generation_confirmation_message_id':card}
        rejected=events(client.post(f'/api/chat/sessions/{qa_id}/assistant:stream',json=bad))
        assert rejected[-1][1]['code']=='personal_generation_confirmation_invalid'
        assert client.get(f'/api/chat/sessions/{study_id}/messages',params={'purpose':'study'}).json()==before
        assert client.patch(f'/api/chat/sessions/{qa_id}',json={'title':'已重命名独立讨论'}).status_code==200
        assert any(s['title']=='已重命名独立讨论' for s in client.get('/api/chat/sessions?purpose=qa').json())
        assert client.delete(f'/api/chat/sessions/{qa_id}').status_code==204
        assert client.get(f'/api/chat/sessions/{study_id}/messages',params={'purpose':'study'}).json()==before
        assert model.calls==0
