from uuid import UUID

from backend.services import study_read_context as reads


def test_shared_policy_context_loads_only_missing_ids_for_one_session(monkeypatch):
    db=object()
    first=UUID(int=1); second=UUID(int=2); third=UUID(int=3)
    loaded=[]

    def fake_load(session,ids):
        assert session is db
        ids=set(ids)
        loaded.append(ids)
        return reads.PolicyReadContext(
            policy_rows={key:key for key in ids},
            states={key:key for key in ids},
            versions={(key,1):key for key in ids},
            activity_ids=set(ids),
            content_versions={str(key):key for key in ids},
        )

    monkeypatch.setattr(reads,'load_policy_read_context',fake_load)
    monkeypatch.setattr('backend.mastery.storage.policy_for_node',
        lambda session,kp_id,_read_context: _read_context.policy_rows.get(kp_id))

    with reads.shared_policy_read_context(db):
        first_result,context_a=reads.policies_for_nodes(db,[first,second],include_missing=True)
        overlap_result,context_b=reads.policies_for_nodes(db,[second,third],include_missing=True)
        subset_result,context_c=reads.policies_for_nodes(db,[first],include_missing=True)

    assert loaded==[{first,second},{third}]
    assert context_a is context_b is context_c
    assert context_c.policy_rows=={first:first,second:second,third:third}
    assert set(first_result)=={first,second}
    assert set(overlap_result)=={second,third}
    assert set(subset_result)=={first}
    assert context_c.states=={first:first,second:second,third:third}
    assert context_c.activity_ids=={first,second,third}
