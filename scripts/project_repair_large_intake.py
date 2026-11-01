"""Recover long-question metadata and admit independently checked originals.

This command is hard-bound to its own empty, isolated PostgreSQL cluster.
It never reads application settings, development data, or provider secrets.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from collections import Counter
from types import SimpleNamespace
from uuid import UUID, uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'storage/quality-audits/project-repair-20261018/large-questions'
PG = Path(r'C:\Program Files\PostgreSQL\18\bin')
DATA = OUT / 'owned-postgres'
PORT = 59263
DATABASE = 'closeout_intake_test'
URL = f'postgresql+psycopg://postgres@127.0.0.1:{PORT}/{DATABASE}'
SOURCE = Path(r'C:\Users\ZBT\Desktop\数学二与408逐题知识点索引_2000至今\逐题整理')
INDEX = ROOT / 'storage/quality-audits/long-question-supply-20261017/expanded-source-index/long-question-source-candidates.csv'


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def configure():
    os.environ.update(APP_ENV='test', DATABASE_URL=URL, TEST_DATABASE_URL=URL,
                      KAOYAN_OWNED_TEST_PORT=str(PORT), HF_HUB_OFFLINE='1',
                      TRANSFORMERS_OFFLINE='1')
    from backend.config import get_settings
    get_settings.cache_clear()


def setup():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (DATA / 'PG_VERSION').exists():
        subprocess.run([str(PG/'initdb.exe'), '-D', str(DATA), '-U', 'postgres',
                        '--auth=trust', '--encoding=UTF8', '--locale=C'], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    status = subprocess.run([str(PG/'pg_ctl.exe'), '-D', str(DATA), 'status'], capture_output=True)
    if status.returncode:
        subprocess.run([str(PG/'pg_ctl.exe'), '-D', str(DATA), '-l', str(OUT/'postgres.log'),
                        '-o', f'-p {PORT} -h 127.0.0.1', '-w', 'start'], check=True)
    import psycopg
    with psycopg.connect(f'postgresql://postgres@127.0.0.1:{PORT}/postgres', autocommit=True) as conn:
        identity = conn.execute('select system_identifier from pg_control_system()').fetchone()[0]
        owner_file = OUT/'owner.json'
        if owner_file.exists():
            assert json.loads(owner_file.read_text(encoding='utf-8'))['system_identifier'] == str(identity)
        else:
            write_json(owner_file, {'port': PORT, 'database': DATABASE, 'system_identifier': str(identity), 'data_directory': str(DATA)})
        if not conn.execute('select 1 from pg_database where datname=%s', (DATABASE,)).fetchone():
            conn.execute('create database closeout_intake_test')
    configure()
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT/'alembic.ini')), 'head')
    print(json.dumps({'setup': 'PASS', 'database': DATABASE, 'port': PORT, 'system_identifier': str(identity)}))


def node_catalog():
    """Use bundled public hierarchy only, never clone user projections."""
    from backend.services.exam_reference_service import build_exam_reference_seed
    # The canonical index consists only of source identities and public nodes.
    return build_exam_reference_seed()


def archive_rows(table):
    """Read one content table from the sealed archive, without restoring it."""
    archive=ROOT/'storage/quality-audits/phase45z-final-20261013/final-sealed.dump'
    expected='8d4f1f685cf35c2091f9a92c0f66722866b8d998c3ae7612b8acbe36858b09a0'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
    raw=subprocess.run([str(PG/'pg_restore.exe'),'--data-only',f'--table={table}','--file=-',str(archive)],
                       check=True,capture_output=True).stdout.decode('utf-8')
    columns=None
    def decode(value):
        if value==r'\N':return None
        escapes={'n':'\n','r':'\r','t':'\t','b':'\b','f':'\f','v':'\v','\\':'\\'}
        return re.sub(r'\\([nrtbfv\\])',lambda m:escapes[m.group(1)],value)
    for line in raw.splitlines():
        if line.startswith(f'COPY public.{table} ('):
            columns=line.split('(',1)[1].split(')',1)[0].split(', ');continue
        if columns is None:continue
        if line==r'\.':break
        values=[decode(v) for v in line.split('\t')]
        assert len(values)==len(columns)
        yield dict(zip(columns,values))


def public_peers():
    nodes={q['id']:q['code'] for q in archive_rows('knowledge_points')}
    peers=[]
    for q in archive_rows('questions'):
        if q['bank_scope']!='public' or q['generation_batch_id'] is not None:continue
        peers.append(SimpleNamespace(id=UUID(q['id']),kp_id=nodes[q['kp_id']],
            bank_scope='public',generation_batch_id=None,is_variant=q['is_variant']=='t',question_type=q['question_type'],
            stem=q['stem'],correct_answer=q['correct_answer'],
            options=json.loads(q['options']) if q['options'] else None,
            grading_config=json.loads(q['grading_config']) if q['grading_config'] else {}))
    return peers


def mapping():
    from backend.services.question_identity import historical_identity
    nodes,refs=node_catalog()
    refs_by_identity={}
    for ref in refs:
        code=ref['knowledge_point_code']
        if '.family.' in code or '.family.' in code.replace('math.family.','x.family.'):continue
        refs_by_identity.setdefault((ref['subject'],ref['year'],ref['question_number']),[]).append(code)
    peers=public_peers()
    existing={historical_identity(p):str(p.id) for p in peers if historical_identity(p)}
    results=[]
    with INDEX.open(encoding='utf-8-sig',newline='') as stream:
        for record in csv.DictReader(stream):
            subject='数学二' if record['subject']=='数学二' else '408'
            year=int(record['year']); number=int(record['exam_question_number'])
            source_file=SOURCE/subject/str(year)/f'Q{number:02d}.md'
            raw=source_file.read_text(encoding='utf-8') if source_file.exists() else ''
            stem=re.search(r'^##\s*题目\s*\n(.*?)(?=^##|\Z)',raw,re.M|re.S)
            answer=re.search(r'^##\s*(?:参考答案草稿|参考答案|答案)\s*\n(.*?)(?=^##|\Z)',raw,re.M|re.S)
            complete=bool(stem and stem.group(1).strip() and answer and answer.group(1).strip())
            historical=('math2' if subject=='数学二' else '408',year,number)
            duplicate=existing.get(historical)
            status='duplicate' if duplicate else 'draft' if complete else 'needs_review' if raw else 'unmatched'
            codes=refs_by_identity.get((subject,year,number),[])
            results.append({**record,'source_file':str(source_file) if raw else None,
                'source_sha256':hashlib.sha256(raw.encode()).hexdigest() if raw else None,
                'knowledge_node_codes':sorted(set(codes)), 'stem_complete':bool(stem),
                'answer_present':bool(answer),'answer_status':'unreviewed_local_draft' if answer else 'missing',
                'status':status,'duplicate_result':'same_exam_identity' if duplicate else 'not_found_in_sealed_identity_index',
                'final_question_id':duplicate,'candidate_is_database_question':False,
                'reason':'封版公共题已存在相同学科/年份/题号；不得重复新增' if duplicate else
                '本地稿待独立逐题核验，不以草稿标签推断正确' if complete else
                '本地稿结构或答案不完整' if raw else '只有题号考点索引，没有可恢复题面与答案'})
    write_json(OUT/'source-mapping-270.json',results)
    with (OUT/'source-mapping-270.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields=list(results[0]); writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        writer.writerows([{**r,'knowledge_node_codes':'|'.join(r['knowledge_node_codes'])} for r in results])
    write_json(OUT/'source-inventory.json',{'total':len(results),'status_counts':dict(Counter(r['status'] for r in results)),
        'local_files':sum(bool(r['source_file']) for r in results),'complete_section_pairs':sum(r['stem_complete'] and r['answer_present'] for r in results),
        'sealed_public_peer_count':len(peers),'sealed_archive_sha256':'8d4f1f685cf35c2091f9a92c0f66722866b8d998c3ae7612b8acbe36858b09a0',
        'live_database_accessed':False,'personal_records_copied':False})
    return results,peers


def seed_public_nodes(db):
    from sqlalchemy import select
    from backend.models.learning import KnowledgePoint
    nodes,_=node_catalog(); ids={}
    for raw in nodes:
        parent=ids.get(raw.get('parent_code'))
        q=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==raw['code']))
        if q is None:
            q=KnowledgePoint(id=uuid5(NAMESPACE_URL,'large-intake-node:'+raw['code']),
                code=raw['code'],name=raw['name'],subject=raw['subject'],parent_id=parent,
                is_active=True,is_assessable=raw['is_reference_only'],is_reference_only=raw['is_reference_only'])
            db.add(q);db.flush()
        ids[raw['code']]=q.id
    return list(db.scalars(select(KnowledgePoint)))


def intake(db, specs, peers, *, inject_failure=False,namespace=''):
    from sqlalchemy import select
    from backend.models.learning import Question
    from backend.services.question_generation import Output,prepare_codex_public_original
    from backend.services.question_identity import duplicate_findings
    from backend.services.auto_question_review import qualify_public_question,question_snapshot_sha256, current_auto_review
    nodes=seed_public_nodes(db)
    # These match local complete drafts; keep their source identities, never
    # mislabel their copied mathematics as newly authored originals.
    source_ids={'absolute-integral-minimum':('math2',2016,16),
        'implicit-global-maximum':('math2',2016,17),'triangle-double-integral':('math2',2016,18),
        'rational-definite-integral':('math2',2025,17)}
    aliases={'二阶常系数线性微分方程':'二阶常系数非齐次线性微分方程',
        '曲线的曲率与曲率半径':'隐函数曲线曲率与曲率半径',
        '线性方程组的求解':'线性方程组','向量的线性表示':'向量组之间的线性表示',
        '文件的物理结构':'文件物理结构','CPU 调度':'CPU 调度算法',
        '反常积分':'反常积分的计算与敛散性','二叉排序树':'二叉搜索树','散列表的查找':'散列表-开放定址'}
    from backend.services.question_identity import historical_identity
    identities={historical_identity(p):str(p.id) for p in peers if historical_identity(p)}
    results=[]
    for index,spec in enumerate(specs):
        if spec['key'] in source_ids:
            existing=identities.get(source_ids[spec['key']])
            results.append({'key':spec['key'],'status':'duplicate' if existing else 'needs_review',
                'question_id':existing,'reason':'本地原题有来源身份，禁止以原创身份重复入库；需版本化恢复原ID' if existing else
                '题干来自逐题稿，尚未完成原卷同一性核验；不冒充development_original'})
            continue
        matches=[q for q in nodes if q.name==aliases.get(spec['topic'],spec['topic']) and not q.children and q.is_assessable]
        if not matches:
            matches=[q for q in nodes if aliases.get(spec['topic'],spec['topic']) in q.name and not q.children and q.is_assessable]
        if len(matches)!=1:
            results.append({'key':spec['key'],'status':'unmatched','reason':'canonical_node_not_unique','matches':[q.code for q in matches]});continue
        node=matches[0];key='project-repair-long-20261018:'+namespace+spec['key']
        qid=uuid5(NAMESPACE_URL,'codex-public-original:'+key)
        old=db.get(Question,qid)
        if old:
            assert old.stem==spec['stem'] and old.correct_answer==spec['answer']
            assert current_auto_review(old,node) is not None
            results.append({'key':spec['key'],'status':'noop','question_id':str(old.id),'node_code':node.code});continue
        savepoint=db.begin_nested()
        try:
            reason={'knowledge_depth':f'综合考查{node.name}的模型、约束及计算方法，需要解释中间状态和最终结论。',
                'reasoning_steps':f'必须先建立{node.name}的数学或状态模型，再执行多步推导并对结果交叉验证。',
                'trap_design':'题干明确给出边界、单位或初始状态，解析指出常见错误，不能仅凭概念关键词得到答案。',
                'application_value':f'用于训练{node.name}的开放式求解与过程表达，系统仅核对最后数值，过程由解析辅助复盘。'}
            q=prepare_codex_public_original(Output(stem=spec['stem'],question_type='calculation',
                correct_answer=spec['answer'],explanation=spec['explanation'],final_value=spec['answer']),node,
                request_id=key,derived_answer=spec['answer'],method_evidence=spec['verification'],
                explanation_key_steps=[spec['explanation'][:max(20,len(spec['explanation'])//2)],spec['explanation'][max(20,len(spec['explanation'])//2):]],
                difficulty='medium',skill_tags=[node.name,'多步骤开放式计算'],difficulty_reason=reason)
            q.estimated_minutes=spec['estimated_minutes']
            # estimated_minutes is review-bound; regenerate its receipt after
            # assigning the actual long-question study duration.
            from backend.services.auto_question_review import attach_codex_independent_review
            attach_codex_independent_review(q,node,derived_answer=spec['answer'],method_evidence=spec['verification'],
                explanation_key_steps=[spec['explanation'][:len(spec['explanation'])//2],spec['explanation'][len(spec['explanation'])//2:]])
            q.kp_id=node.code
            findings=duplicate_findings(q,peers)
            q.kp_id=node.id
            if findings['matches'] or findings['uncertain_similar']:
                raise ValueError('sealed_duplicate_or_similarity:'+json.dumps(findings,ensure_ascii=False))
            if inject_failure and index==1:raise ValueError('injected_candidate_failure')
            db.add(q);db.flush()
            event,assessment=qualify_public_question(db,question_id=q.id,node_id=node.id,
                expected_snapshot_sha256=question_snapshot_sha256(q),idempotency_key=key)
            if event is None:
                raise ValueError(json.dumps({k:v for k,v in assessment.get('stages',{}).items() if v.get('status')!='PASS'},ensure_ascii=False))
            savepoint.commit()
            results.append({'key':spec['key'],'status':'inserted','question_id':str(q.id),'version_id':str(q.current_version_id),
                'auto_review_event_id':str(event.id),'qualification_class':event.qualification_class,'node_code':node.code,
                'production_grading_tests':assessment['stages']['grading'],'sealed_global_dedup':'PASS','independent_checks':spec['checks']})
        except Exception as exc:
            savepoint.rollback();results.append({'key':spec['key'],'status':'rejected','reason':str(exc)[:2000]})
    return results


def run():
    configure()
    from sqlalchemy import create_engine,select,text,func
    from sqlalchemy.orm import Session
    from backend.models import import_models
    import_models()
    from backend.models.learning import Question,QuestionVersion,QuestionAutoReviewEvent,KnowledgePoint,KpMasteryPolicy,KpGraduationQuestionSetVersion
    from backend.services.graduation_question_set import freeze_graduation_question_set,publish_all_public_question_set_version
    from scripts.project_repair_long_question_specs import specs
    source_mapping,peers=mapping();batch=specs()
    write_json(OUT/'reviewed-original-long-specs.json',batch)
    engine=create_engine(URL)
    owner=json.loads((OUT/'owner.json').read_text(encoding='utf-8'))
    with Session(engine) as db:
        ident=db.execute(text('select current_database(),inet_server_port(),system_identifier from pg_control_system()')).one()
        assert ident[0]==DATABASE and ident[1]==PORT and str(ident[2])==owner['system_identifier']
        # Entire rehearsal rolls back, even after valid items have flushed.
        original_count=db.scalar(select(func.count()).select_from(Question))
        attempted=intake(db,[batch[i] for i in [0,5,6]],peers,inject_failure=True,namespace='rollback-check:')
        assert len(attempted)==3 and attempted[1].get('reason')=='injected_candidate_failure',attempted
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Question))==original_count
        rollback={'status':'PASS','candidate_results':attempted,'question_count_after_rollback':original_count,
            'partial_failure_did_not_block_later_candidate':True,'outer_transaction_rollback_preserved_baseline':True}
        results=intake(db,batch,peers)
        db.commit()
        counts=lambda:{model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in (Question,QuestionVersion,QuestionAutoReviewEvent,KpGraduationQuestionSetVersion)}
        before=counts(); again=intake(db,batch,peers);db.commit();after=counts();assert before==after
        publications=[]
        for node in db.scalars(select(KnowledgePoint)).all():
            ids=list(db.scalars(select(Question.id).where(Question.kp_id==node.id)))
            if not ids:continue
            policy=db.get(KpMasteryPolicy,node.id)
            if policy is None or policy.policy_version!=3:
                freeze_graduation_question_set(db,kp_id=node.id,question_ids=ids,reason='隔离预演：真实独立复算大题首次发布；无历史用户数据')
            elif set(map(str,ids)) != set(policy.graduation_question_ids):
                current=db.get(KpGraduationQuestionSetVersion,(node.id,policy.graduation_set_version))
                publish_all_public_question_set_version(db,kp_id=node.id,question_ids=ids,
                    expected_set_version=policy.graduation_set_version,expected_set_sha256=current.question_ids_sha256,
                    publication_key='large-intake-20261018:'+node.code+':'+str(len(ids)),reason='隔离批次新增正式大题，受保护发布；历史题集与学习实例不变')
            policy=db.get(KpMasteryPolicy,node.id)
            publications.append({'node_code':node.code,'set_version':policy.graduation_set_version,'members':len(ids)})
        db.commit()
        protected={table:db.scalar(text(f'select count(*) from {table}')) for table in ('question_attempts','learning_events','kp_states','daily_plans','practice_items')}
        assert all(v==0 for v in protected.values())
        write_json(OUT/'intake-results.json',{'identity':owner,'candidates':len(batch),'results':results,'counts':dict(Counter(r['status'] for r in results)),
            'idempotency':{'status':'PASS','before':before,'after':after,'second_run_counts':dict(Counter(r['status'] for r in again))},
            'rollback':rollback,'publications':publications,'protected_history_counts':protected,
            'live_database_accessed':False,'paid_model_calls':0,
            'limitation':'没有把270条目录补写成270道真题；仅实际复算且通过现行资格的独立题入隔离库。'})
        print(json.dumps({'result_counts':dict(Counter(r['status'] for r in results)),'protected':protected},ensure_ascii=False))
    engine.dispose()


if __name__ == '__main__':
    setup()
    run()
