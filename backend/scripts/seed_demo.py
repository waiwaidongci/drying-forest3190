import json,random,logging
from sqlalchemy import select,func
from src.config.database import Base,engine,Session
from src.config.settings import CONFIG
from src.models.user import User
from src.models.source import Source
from src.models.record import Record
from src.models.run import Run
from src.models.pair_run import PairRun
from src.models import note,audit
from src.utils.security import hash_password
from src.utils.serialization import now
from src.services.runs import queue
from src.services.pair_runs import QUEUE_NAME as PAIR_QUEUE
from src.services.pairing import digest
from src.services.domain_validation import validate_record

def seed_values(kind,index,batch,rng):
    if kind=='gaussian':
        cls=index%3;return {'rms':round(max(.1,rng.gauss([1.2,3.0,2.0][cls]+batch*.08,.35)),3),'centroid':round(max(100,rng.gauss([900,1600,2300][cls],170)),2),'kurtosis':round(max(.1,rng.gauss([2.8,5.2,3.9][cls],.45)),3),'label':['正常','轴承磨损','转子偏心'][cls]}
    if kind=='density':
        cls=index%3
        if index%19==0:return {'temperature':round(rng.uniform(12,42),2),'humidity':round(rng.uniform(12,92),2),'particles':round(rng.uniform(4,140),2)}
        return {'temperature':round(rng.gauss([19,26,32][cls]+batch*.3,.8),2),'humidity':round(rng.gauss([72,45,28][cls],2.5),2),'particles':round(max(.1,rng.gauss([22,48,85][cls],3)),2)}
    if kind=='transition':
        choices=[['序章','材料','工艺','案例'],['序章','案例','附录'],['材料','工艺','案例','附录'],['序章','材料','案例'],['序章']]
        path=choices[rng.randrange(len(choices))];return {'session':f'SY-{batch+1}-{index+1:04}','path':'>'.join(path)}
    if kind=='forest':
        moisture=rng.uniform(20,60);thickness=rng.uniform(1,8);temperature=rng.uniform(50,100);airflow=rng.uniform(1,5)
        minutes=12+1.6*moisture+8*thickness-.45*temperature-3*airflow+0.1*moisture*thickness+rng.gauss(0,3)
        return {'moisture':round(moisture,2),'thickness':round(thickness,2),'temperature':round(temperature,2),'airflow':round(airflow,2),'minutes':round(max(5,minutes),2)}
    if kind=='neighbors':
        uid=index//6;slot=index%6;exhibit=(uid%3*3+slot)%12
        return {'visitor':f'V{uid+1:03}','exhibit':f'E{exhibit+1:02}','rating':round(max(1,min(5,3+(1 if exhibit%3==uid%3 else -.4)+rng.gauss(0,.55))),1)}

def counts(db):
    return {cls.__tablename__:db.scalar(select(func.count()).select_from(cls)) for cls in (User,Source,Record,Run,PairRun)}
def pair_snapshot(db,source_a,source_b,label_a,label_b,humidity,thickness):
    rows=db.scalars(select(Record).where(Record.source_id.in_([source_a.id,source_b.id])).order_by(Record.id)).all()
    grouped={source_a.id:[],source_b.id:[]}
    for r in rows:grouped[r.source_id].append({'id':r.id,'source_id':r.source_id,'reference':r.reference,'values':r.values})
    return {'source_a':{'id':source_a.id,'name':source_a.name,'filename':source_a.filename},
            'source_b':{'id':source_b.id,'name':source_b.name,'filename':source_b.filename},
            'label_a':label_a,'label_b':label_b,'tolerance_humidity':humidity,'tolerance_thickness':thickness,
            'records_a':grouped[source_a.id],'records_b':grouped[source_b.id],
            'frozen_counts':{'a':len(grouped[source_a.id]),'b':len(grouped[source_b.id])},
            'checksum':digest({'a':grouped[source_a.id],'b':grouped[source_b.id],'humidity':humidity,'thickness':thickness})}
def seed():
    Base.metadata.create_all(engine);rng=random.Random(42);queued=[];paired=[]
    with Session() as db:
        for role in ('admin','analyst','viewer'):
            email=role+'@'+CONFIG['slug']+'.demo'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password_hash=hash_password('Research2026!'),role=role))
        for batch in range(3):
            key=CONFIG['code']+f'-202611-{batch+1:02}'
            source=db.scalar(select(Source).where(Source.key==key))
            if not source:
                source=Source(key=key,name=key+' '+['秋季常规组','复测对照组','工艺观察组'][batch],filename=CONFIG['slug']+f'-202611-{batch+1:02}.csv',description=CONFIG['scenario']);db.add(source);db.flush()
            for index in range(CONFIG['seed_count']):
                reference=key+f'-{index+1:04}'
                vals=seed_values(CONFIG['algorithm'],index,batch,rng)
                if not db.scalar(select(Record.id).where(Record.source_id==source.id,Record.reference==reference)):
                    db.add(Record(source_id=source.id,reference=reference,values=validate_record(vals)))
            db.flush()
            if batch==0 and not db.scalar(select(Run.id).where(Run.name=='首轮种子研究')):
                records=[{'id':r.id,'source_id':r.source_id,'reference':r.reference,'values':r.values} for r in db.scalars(select(Record).where(Record.source_id==source.id).order_by(Record.id))]
                run=Run(source_id=source.id,name='首轮种子研究',state='queued',parameters=CONFIG['default_parameters'],snapshot={'source':{'id':source.id,'name':source.name,'filename':source.filename},'records':records},created_at=now());db.add(run);db.flush();queued.append(run.id)
        db.flush()
        source_a=db.scalar(select(Source).where(Source.key==CONFIG['code']+'-202611-01'))
        source_b=db.scalar(select(Source).where(Source.key==CONFIG['code']+'-202611-02'))
        if not db.scalar(select(PairRun.id).where(PairRun.name=='首轮工艺配对对照')):
            snapshot=pair_snapshot(db,source_a,source_b,'现用工艺','备用工艺','3','0.8')
            pair=PairRun(name='首轮工艺配对对照',source_a_id=source_a.id,source_b_id=source_b.id,label_a='现用工艺',label_b='备用工艺',
                         tolerance_humidity='3',tolerance_thickness='0.8',state='queued',snapshot=snapshot,created_at=now(),updated_at=now())
            db.add(pair);db.flush();paired.append(pair.id)
        db.commit();print(json.dumps(counts(db),ensure_ascii=False))
    for id in queued:
        try:queue.rpush('analysis:queue',id)
        except Exception:logging.exception('seed queue unavailable')
    for id in paired:
        try:queue.rpush(PAIR_QUEUE,id)
        except Exception:logging.exception('seed pairing queue unavailable')
if __name__=='__main__':seed()
