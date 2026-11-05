"""Marked _test schema only; simulated production can never certify graduation."""
from copy import deepcopy
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from backend.models.learning import Question,KnowledgePoint
from backend.services.question_generation import promote,generate,assess_output,Budget,generation_hash
from backend.services.question_verification_upgrade import snapshot
from scripts.run_question_repair_pilot import isolated_factory
from scripts.run_question_generation_pilot import FixtureModel
from tests.unit.test_question_generation import node,parent


def test_generated_new_and_completion_are_idempotent_rollbackable_and_guarded(test_database_url):
    n=node(); p=parent(n,"")
    with isolated_factory(test_database_url) as (factory,schema):
        with factory.begin() as db:
            db.add(n);db.flush();db.add(p);db.flush();before=deepcopy(snapshot(p))
            request={"family":"historic_fifth_derivative","mode":"completion","question_type":"fill_blank","parent":{"stem":p.stem}}
            out,trace=generate(FixtureModel(),request,Budget())
            c=assess_output(out,n,request_id="TEST_FIXTURE completion",mode="completion",family="historic_fifth_derivative",parent=p,trace=trace)
            nested=db.begin_nested()
            fixed,status=promote(db,c,n)
            assert status=="ISOLATED_COMPLETION_APPLIED" and fixed.id==p.id and fixed.correct_answer=="31e"
            assert promote(db,c,n)[1]=="NOOP"
            assert fixed.question_provenance=="legacy_unknown" and fixed.answer_verification_event_id is None
            nested.rollback(); db.expire_all()
            assert snapshot(db.get(Question,p.id))==before
            req={"family":"power_derivative","sample":2,"question_type":"single_choice"}
            out,trace=generate(FixtureModel(),req,Budget())
            c=assess_output(out,n,request_id="TEST_FIXTURE original",mode="original",family="power_derivative",trace=trace)
            q,status=promote(db,c,n)
            assert status=="ISOLATED_NEW_QUESTION" and q.question_provenance=="ai_generated_practice"
            assert promote(db,c,n)[1]=="NOOP"
            q.explanation+=" changed version";db.flush()
            with pytest.raises(ValueError):promote(db,c,n)
        with factory() as db:
            from sqlalchemy import text
            db.execute(text("SET search_path=public"))
            with pytest.raises(ValueError,match="isolated _test"):promote(db,c,n)
