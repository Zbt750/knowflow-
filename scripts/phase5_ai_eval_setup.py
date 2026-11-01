"""Create a new owned local test cluster and selectively copy frozen public content.

Never connects to port 5433. No model calls. Original frozen files stay unchanged.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "storage/quality-audits/phase5-closeout-execution-20261015/ai-test"
PORT = 59271
PG = Path(r"C:\Program Files\PostgreSQL\18\bin")
SOURCE = "phase5_closeout_source_test"
BASE = "phase5_closeout_base_test"


def url(name):
    return f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{name}"


def run(command, name, env=None):
    with (OUT / name).open("xb") as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
    if result.returncode:
        raise RuntimeError(f"setup_failed:{name}:{result.returncode}")


def main():
    assert PORT > 18000 and PORT != 5433 and not OUT.exists()
    dump = ROOT / "storage/quality-audits/phase45z-final-20261013/final-sealed.dump"
    expected = json.loads((ROOT / "eval/phase5-closeout-v1/fixtures.json").read_text(encoding="utf-8"))["content_source"]["sha256"]
    assert hashlib.sha256(dump.read_bytes()).hexdigest() == expected
    OUT.mkdir(parents=True)
    run([str(PG / "initdb.exe"), "-D", str(OUT / "data"), "-U", "postgres", "-E", "UTF8", "--locale=C", "-A", "trust"], "initdb.log")
    run([str(PG / "pg_ctl.exe"), "-D", str(OUT / "data"), "-l", str(OUT / "postgresql.log"), "-o", f"-p {PORT} -h 127.0.0.1", "-w", "start"], "start.log")
    import psycopg
    with psycopg.connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres", autocommit=True) as c:
        identity = c.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone()[0]
        assert identity != "7686825087296682120"
        for name in (SOURCE, BASE):
            c.execute(f'CREATE DATABASE "{name}"')
    marker = {"owner": "phase5-closeout-authorized-eval-v1", "port": PORT, "system_identifier": identity, "data": str(OUT / "data"), "source_hash": expected}
    (OUT / "owner.json").write_text(json.dumps(marker, indent=2), encoding="utf-8")
    run([str(PG / "pg_restore.exe"), "--exit-on-error", "--no-owner", "--no-privileges", "-h", "127.0.0.1", "-p", str(PORT), "-U", "postgres", "-d", SOURCE, str(dump)], "restore-frozen-source.log")
    for name in (SOURCE, BASE):
        env = dict(os.environ, APP_ENV="test", TEST_DATABASE_URL=url(name), DATABASE_URL=url(name), KAOYAN_OWNED_TEST_PORT=str(PORT))
        run([sys.executable, "-m", "alembic", "upgrade", "head"], f"migrate-{name}.log", env)
    os.environ.update(APP_ENV="test", TEST_DATABASE_URL=url(BASE), DATABASE_URL=url(BASE), KAOYAN_OWNED_TEST_PORT=str(PORT))
    from sqlalchemy import create_engine, select, update
    from sqlalchemy.orm import Session, joinedload
    from backend.models import import_models
    from backend.models.base import Base as Models
    from backend.models.learning import Question
    from backend.services.auto_question_review import current_auto_review
    import_models()
    source = create_engine(url(SOURCE))
    target = create_engine(url(BASE))
    with Session(source) as db:
        all_questions = list(db.scalars(select(Question).options(joinedload(Question.kp), joinedload(Question.current_auto_review))))
        formal = [q for q in all_questions if current_auto_review(q, q.kp) is not None]
        ids = {q.id for q in formal}
        assert len(ids) == 1804
        tables = Models.metadata.tables
        payload = {}
        for name in ("knowledge_points", "kp_mastery_policies", "questions", "question_versions", "question_auto_review_events", "kp_graduation_question_set_versions", "question_source_attestations"):
            table = tables[name]
            statement = select(table)
            if "question_id" in table.c:
                statement = statement.where(table.c.question_id.in_(ids))
            elif name == "questions":
                statement = statement.where(table.c.id.in_(ids))
            payload[name] = [dict(row) for row in db.execute(statement).mappings()]
    with target.begin() as c:
        nodes = payload["knowledge_points"]
        done = set()
        while nodes:
            ready = [n for n in nodes if n["parent_id"] is None or n["parent_id"] in done]
            assert ready
            c.execute(tables["knowledge_points"].insert(), ready)
            done.update(n["id"] for n in ready)
            nodes = [n for n in nodes if n["id"] not in done]
        questions = payload["questions"]
        assert all(q["answer_verification_event_id"] is None and q["generation_batch_id"] is None for q in questions)
        c.execute(tables["questions"].insert(), [{**q, "auto_review_event_id": None, "current_version_id": None} for q in questions])
        c.execute(tables["question_versions"].insert(), payload["question_versions"])
        reviews = payload["question_auto_review_events"]
        inserted = set()
        while reviews:
            ready = [r for r in reviews if r["related_event_id"] is None or r["related_event_id"] in inserted]
            assert ready
            c.execute(tables["question_auto_review_events"].insert(), ready)
            inserted.update(r["id"] for r in ready)
            reviews = [r for r in reviews if r["id"] not in inserted]
        for q in questions:
            c.execute(update(tables["questions"]).where(tables["questions"].c.id == q["id"]).values(current_version_id=q["current_version_id"], auto_review_event_id=q["auto_review_event_id"]))
        for name in ("kp_mastery_policies", "kp_graduation_question_set_versions", "question_source_attestations"):
            if payload[name]:
                c.execute(tables[name].insert(), payload[name])
    source.dispose()
    target.dispose()
    marker["content_rows_copied"] = {n: len(v) for n, v in payload.items()}
    marker["learner_rows_copied"] = 0
    (OUT / "setup.json").write_text(json.dumps(marker, indent=2), encoding="utf-8")
    print(json.dumps(marker, ensure_ascii=True))


if __name__ == "__main__":
    main()
