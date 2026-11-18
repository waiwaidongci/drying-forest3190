"""配对对照任务的受理、冻结、执行与发布。

受理时在同一条查询里读取两组试件，连同湿度/厚度容差一起写入冻结快照；
之后补录的样本不会进入这次对照。worker 先落盘配对名单，再计算区间，
中断后重试沿用同一份快照与同一份配对名单。
"""
from fastapi import HTTPException
from sqlalchemy import select,update
from redis import Redis

from ..config.settings import REDIS_URL
from ..models.pair_run import PairRun
from ..models.record import Record
from ..models.source import Source
from ..utils.serialization import row,now
from .audit import log
from .pairing import compute_pairing,compute_estimate,pair_rows,digest
from .pairing_limits import check_tolerances

queue=Redis.from_url(REDIS_URL)
QUEUE_NAME='pairing:queue'
MAX_GROUP=1000

def get_pair_run(db,id):
    r=db.get(PairRun,id)
    if not r:raise HTTPException(404,'未找到配对对照任务')
    return r

def _source_or_404(db,id,role):
    s=db.get(Source,id)
    if not s:raise HTTPException(404,f'未找到{role}来源')
    return s

def _frozen_records(db,source_ids):
    """单条语句读取两组试件，保证补录与冻结之间只有一个一致截点。"""
    rows=db.scalars(select(Record).where(Record.source_id.in_(source_ids)).order_by(Record.id)).all()
    grouped={id:[] for id in source_ids}
    for r in rows:grouped[r.source_id].append(row(r))
    return grouped

def create_pair_run(db,user,data):
    if data.source_a_id==data.source_b_id:raise HTTPException(422,'两组必须来自不同来源，才能形成独立对照')
    source_a=_source_or_404(db,data.source_a_id,'A组')
    source_b=_source_or_404(db,data.source_b_id,'B组')
    try:
        tolerance_humidity,tolerance_thickness=check_tolerances(data.tolerance_humidity,data.tolerance_thickness)
    except ValueError as e:raise HTTPException(422,str(e))
    grouped=_frozen_records(db,[source_a.id,source_b.id])
    records_a=grouped[source_a.id];records_b=grouped[source_b.id]
    if len(records_a)<2 or len(records_b)<2:raise HTTPException(422,'两组都至少需要2件试件，才能形成配对并估计区间')
    if len(records_a)>MAX_GROUP or len(records_b)>MAX_GROUP:raise HTTPException(422,'单组试件不能超过1000件，请拆成多轮对照')
    snapshot={
        'source_a':row(source_a),'source_b':row(source_b),
        'label_a':data.label_a or 'A组','label_b':data.label_b or 'B组',
        'tolerance_humidity':tolerance_humidity,'tolerance_thickness':tolerance_thickness,
        'records_a':records_a,'records_b':records_b,
        'frozen_counts':{'a':len(records_a),'b':len(records_b)},
        'checksum':digest({'a':records_a,'b':records_b,'humidity':tolerance_humidity,'thickness':tolerance_thickness}),
    }
    r=PairRun(name=data.name,source_a_id=source_a.id,source_b_id=source_b.id,label_a=snapshot['label_a'],label_b=snapshot['label_b'],
              tolerance_humidity=tolerance_humidity,tolerance_thickness=tolerance_thickness,state='queued',snapshot=snapshot,
              created_at=now(),updated_at=now())
    db.add(r);db.flush();log(db,user,'pair_run.queued',r.id,data.name);db.commit()
    try:queue.rpush(QUEUE_NAME,r.id)
    except Exception:
        r.state='failed';r.error='队列暂不可用，请稍后重试；冻结样本已保留';r.updated_at=now();db.commit();raise HTTPException(503,r.error)
    return _public(r)

def list_pair_runs(db):
    items=[]
    for r in db.scalars(select(PairRun).order_by(PairRun.id.desc())):
        base=_public(r)
        base.pop('pairs',None);base.pop('unmatched',None);base.pop('result',None)
        base['frozen_counts']=r.snapshot['frozen_counts']
        base['label_a']=r.snapshot['label_a'];base['label_b']=r.snapshot['label_b']
        items.append(base)
    return items

def retry_pair_run(db,user,id):
    r=get_pair_run(db,id)
    if r.state=='completed':raise HTTPException(409,'该对照已发布，不能重复执行')
    if r.state not in ('queued','running','estimating','failed'):raise HTTPException(409,'当前状态不能重试')
    r.state='queued';r.error='';r.updated_at=now()
    log(db,user,'pair_run.retry',r.id,'沿用冻结样本与已存配对' if r.pairs is not None else '沿用冻结样本重新选对')
    db.commit()
    try:queue.rpush(QUEUE_NAME,r.id)
    except Exception:
        r.state='failed';r.error='队列暂不可用，请稍后重试';db.commit();raise HTTPException(503,r.error)
    return _public(r)

def claim(db,id):
    """原子领取待执行任务，避免重复消息并发执行。"""
    result=db.execute(update(PairRun).where(PairRun.id==id,PairRun.state=='queued').values(state='running',updated_at=now()))
    db.commit()
    if result.rowcount!=1:return None
    return db.get(PairRun,id)

def _public(r):
    base=row(r)
    base.pop('snapshot',None)
    if r.state!='completed':
        base['pairs']=None;base['unmatched']=None;base['result']=None
        base['published_at']=None
    return base

def detail(db,id):
    r=get_pair_run(db,id)
    data=_public(r)
    data['snapshot']={'source_a':r.snapshot['source_a'],'source_b':r.snapshot['source_b'],'label_a':r.snapshot['label_a'],'label_b':r.snapshot['label_b'],
                      'tolerance_humidity':r.snapshot['tolerance_humidity'],'tolerance_thickness':r.snapshot['tolerance_thickness'],
                      'frozen_counts':r.snapshot['frozen_counts'],'checksum':r.snapshot['checksum']}
    if r.state=='completed' and r.pairs is not None and r.result is not None:
        data['rows']=pair_rows(r.pairs,r.snapshot['records_a'],r.snapshot['records_b'])
    else:
        data['rows']=None
    return data

def complete(db,r):
    """配对名单已存在时跳过选对，只用同一份冻结样本估计区间。"""
    if r.state=='completed':return
    if r.pairs is None:
        pairing=compute_pairing(r.snapshot['records_a'],r.snapshot['records_b'],r.snapshot['tolerance_humidity'],r.snapshot['tolerance_thickness'])
        r.pairs=pairing['pairs'];r.unmatched=pairing['unmatched']
        r.result={'pairing_meta':{'candidate_pairs':pairing['candidate_pairs'],'total_normalized_cost':pairing['total_normalized_cost'],
                                  'tolerance_humidity':pairing['tolerance_humidity'],'tolerance_thickness':pairing['tolerance_thickness'],
                                  'tiebreak':pairing['tiebreak'],'tiebreak_applied':pairing['tiebreak']=='reference_order'}}
        r.state='estimating';r.updated_at=now();db.commit()
    estimate=compute_estimate(r.pairs,r.snapshot['records_a'],r.snapshot['records_b'])
    result=dict(r.result or {})
    result['estimate']=estimate
    result['counts']={'a':len(r.snapshot['records_a']),'b':len(r.snapshot['records_b']),'paired':len(r.pairs),'unmatched':len(r.unmatched or [])}
    stamp=now()
    # 只有第一个到达者能发布；重复消息或并发重试不会再次改写发布时间。
    published=db.execute(update(PairRun).where(PairRun.id==r.id,PairRun.state!='completed')
                         .values(result=result,state='completed',published_at=stamp,updated_at=stamp))
    if published.rowcount!=1:
        db.commit();return False
    r.result=result;r.state='completed';r.published_at=stamp;r.updated_at=stamp
    log(db,'worker','pair_run.completed',r.id,f'配对 {len(r.pairs)} 对')
    db.commit()
    return True

def fail(db,r,message):
    stamp=now()
    failed=db.execute(update(PairRun).where(PairRun.id==r.id,PairRun.state!='completed')
                      .values(state='failed',error=message[:2000],updated_at=stamp))
    if failed.rowcount!=1:
        db.commit();return False
    r.state='failed';r.error=message[:2000];r.updated_at=stamp
    log(db,'worker','pair_run.failed',r.id,r.error)
    db.commit()
    return True
