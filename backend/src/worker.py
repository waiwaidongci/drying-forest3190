import json,time,logging,threading
from redis import Redis
from sqlalchemy import select
from .config.database import Session
from .config.settings import REDIS_URL,ARTIFACT_DIR
from .models.run import Run
from .models import source,record,user,note,audit,pair_run
from .services.algorithm import calculate
from .services import pair_runs
from .services.audit import log
from .services.export import csv_response
queue=Redis.from_url(REDIS_URL)
ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
STOP=threading.Event()

def heartbeat():
    while not STOP.wait(5):
        try:(ARTIFACT_DIR/'heartbeat').write_text(str(time.time()))
        except Exception:logging.exception('heartbeat failed')

def execute(id):
    with Session() as db:
        r=db.get(Run,id)
        if not r or r.state!='queued':return
        r.state='running';db.commit()
        try:
            result=calculate(r.snapshot['records'],r.parameters)
            json.dumps(result,allow_nan=False)
            r.result=result;r.state='completed'
            response=csv_response(result,'run.csv')
            (ARTIFACT_DIR/f'run-{r.id}.csv').write_bytes(response.body)
            log(db,'worker','run.completed',r.id)
        except Exception as e:
            logging.exception('analysis failed');r.state='failed';r.error=str(e)[:2000]
            log(db,'worker','run.failed',r.id,r.error)
        db.commit()

def execute_pairing(id):
    with Session() as db:
        r=pair_runs.claim(db,id)
        if not r:return
        try:
            pair_runs.complete(db,r)
        except Exception as e:
            logging.exception('pairing failed')
            pair_runs.fail(db,r,str(e) or '配对对照执行失败')

def main():
    (ARTIFACT_DIR/'heartbeat').write_text(str(time.time()))
    threading.Thread(target=heartbeat,daemon=True).start()
    while True:
        value=queue.blpop(['analysis:queue',pair_runs.QUEUE_NAME],timeout=2)
        if not value:continue
        name,payload=value
        if name==b'analysis:queue':execute(int(payload))
        else:execute_pairing(int(payload))

if __name__=='__main__':main()
