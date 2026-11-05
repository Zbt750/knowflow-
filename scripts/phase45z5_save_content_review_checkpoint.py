"""Save the explicitly read first depth-review batch and factual progress."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'storage/quality-audits/phase45z5-20261013'
OUT=BASE/'final-candidate'
REVIEWS=[
 ('f5553fd8-c0d8-564a-bf76-b65406fbefd0','仅计算二阶行列式ad−bc，答案10正确，缺少参数或结构分析。'),
 ('f205c4e5-6fdf-5d9b-acae-64a959586f0e','多项式定积分直接代原函数，答案4正确，缺少方法选择与条件分析。'),
 ('9bc84813-cf93-546f-a6df-3164cf2a3a07','完全二叉树只代入2i并检查存在，答案下标12正确，过程过短。'),
 ('074e608c-c161-5ab7-bd88-6ab2efe49245','8位补码范围为−128至127，答案正确，但只有基本公式记忆。'),
 ('ee631ef0-f88b-5af7-8b28-1a868460f392','K7边数21正确，单一组合数代入，没有图结构约束推理。'),
 ('adeaf428-d38d-5174-880d-5ef530dbaa5f','只有A与B可互换，拓扑序列2正确，依赖网络规模和分支过小。'),
 ('d1f2be22-3222-5705-ae0b-e17bce55a1fd','矩形上线性函数两次直接积分得5，缺少区域转换或条件选择。'),
 ('65bbf87e-030f-53fa-9064-c0feff7c0cd3','导数3(x²−1)给递减区间(−1,1)，答案正确，缺少参数或综合性质。'),
 ('77ad711f-4102-5d78-a839-656de5648d82','一次洛必达直接得2/3，适用条件明确但不具备较深消去或分类。'),
 ('5ce49e50-b721-5290-8c1f-db119f324488','基本等价无穷小直接得2，缺少高阶消去或替换条件辨析。'),
 ('84c7684f-80de-5934-a899-8d6e19b375d7','指数函数二阶基本展开直接得1/2，缺少多项消去或参数约束。'),
 ('0c10c041-76c1-5057-8006-f141c2f2c5a0','基本极限sin(3x)/x得3，答案正确，训练深度不足。'),
 ('d6d42866-bf43-5240-be29-931f6cc4570a','三个同余键线性探测得下标5，正确但没有删除、失败查找或状态交互。'),
 ('57ecbef9-6856-5f34-9f8b-9e8c76e77794','顺序表单次插入需移2项，正确但只有一个边界公式。'),
 ('623c920d-1eef-5290-b393-b178a133e1c5','线程共享地址空间的结论正确，仅直接概念辨认。'),
 ('7528e718-53cc-5011-897a-edb525b72e3d','互异实特征值保证可对角化，正确但只复述一个基本定理。'),
 ('d182580c-237d-51ab-b4d1-cd69ed4e211f','常数1在矩形上的积分为面积6，正确但无非平凡推导。'),
 ('deaed557-df54-5794-b6f0-b6add89d9b78','抛物线原点曲率2正确，直接两阶导数代入，缺少条件和几何综合。'),
 ('77f850cb-d836-5e47-9790-bbcdc72b7054','可变分区外部碎片的答案正确，仅定义识别，未分析具体分配情境。'),
 ('48b93a12-2ea1-5d60-b135-9bf30212eaf0','ln x二阶导数为负故严格凹，正确但无条件变化或综合考查。'),
]
def main():
 pending_path=OUT/'remaining-depth-review.json'
 rows=json.loads(pending_path.read_text(encoding='utf-8'))
 if [r['id'] for r in rows[:20]]!=[qid for qid,_ in REVIEWS]:raise RuntimeError('frozen_review_order_changed')
 result_path=OUT/'depth-review-first20.json'
 report_path=OUT/'phase45z5-progress.json'
 if result_path.exists() or report_path.exists():raise RuntimeError('existing_review_refuse_overwrite')
 review={'status':'20_REVIEWED_SUBSTANTIVE_UPGRADES_PENDING','reviewer_kind':'AI_ASSISTED_CONTENT_REVIEW',
  'human_verified':False,'source_artifact':pending_path.relative_to(ROOT).as_posix(),
  'source_artifact_sha256':hashlib.sha256(pending_path.read_bytes()).hexdigest(),
  'development_database_accessed':False,'database_mutations':0,
  'results':[{'question_id':qid,'decision':'SUBSTANTIVE_UPGRADE_NEEDED','reason':reason,
    'formal_eligibility_changed':False,'question_version_changed':False} for qid,reason in REVIEWS]}
 result_path.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 final=json.loads((BASE/'originals/batch15-retry1/post-batch-audit.json').read_text(encoding='utf-8'))
 scan=json.loads((OUT/'quality-scan-report.json').read_text(encoding='utf-8'))
 regression=json.loads((OUT/'final-engineering-checks.json').read_text(encoding='utf-8'))
 retry=json.loads((OUT/'regression-retry1/result.json').read_text(encoding='utf-8'))
 original_batches=[json.loads(p.read_text(encoding='utf-8')) for p in (BASE/'originals').glob('batch*/checkpoint.json')]
 added=sum(len(r['accepted']) for r in original_batches)
 sample_upgraded=sum(len(json.loads(p.read_text(encoding='utf-8'))['results']) for p in (BASE/'sample-upgrades').glob('batch*/checkpoint.json'))
 report={'phase':'4.5Z-5','status':'PHASE45Z5_TARGET_REACHED_CONTENT_REVIEW_REMAINING',
  'quantity_target_met':final['formal_questions']>=2000,'final_quality_pass':False,'deployment_ready':False,
  'inventory':{k:final[k] for k in ('formal_questions','formal_subjects','formal_sources','formal_nodes','nonempty_current_sets','current_formal_memberships','node_distribution')},
  'baseline_formal_questions':1753,'new_originals_this_phase':added,'prior_formal_source_risk_holds':4,
  'net_formal_increase':final['formal_questions']-1753,'existing_sample_substantive_upgrades_this_phase':sample_upgraded,
  'sample_keep_decisions':5,'backup':final['backup'],'final_checkpoint':'storage/quality-audits/phase45z5-20261013/originals/batch15-retry1/checkpoint.json',
  'engineering_scan':scan,'initial_regression_counts':regression['counts'],'submission_file_retry_counts':retry['counts'],
  'protected_history':final['protected_history'],'graduation_algorithm_fingerprint':final['graduation_algorithm_fingerprint'],
  'development_5433_accessed':False,'paid_model_calls':0,'next_task':{
    'expand_inventory':False,'review_queue':pending_path.relative_to(ROOT).as_posix(),
    'first_batch_review':result_path.relative_to(ROOT).as_posix(),
    'first_batch_upgrade_pending':20,'historical_heuristic_queue_count':len(rows),
    'fresh_random_sample':'storage/quality-audits/phase45z5-20261013/final-candidate/fresh-original-sample-100.json',
    'fresh_random_sample_review_pending':100}}
 report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'status':report['status'],'formal':final['formal_questions'],'net_increase':report['net_formal_increase'],
  'new_originals':added,'sample_upgrades':sample_upgraded,'content_queue':len(rows),'first20_upgrade_pending':20},ensure_ascii=True))
if __name__=='__main__':main()
