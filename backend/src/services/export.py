import csv,io
from fastapi import HTTPException
from fastapi.responses import Response
from ..models.note import Note
from ..models.pair_run import PairRun
from .runs import get_run
from .pairing import pair_rows

def _csv(rows,columns,filename):
    buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=columns);w.writeheader()
    for r in rows:w.writerow({k:r.get(k,'') for k in columns})
    return Response('﻿'+buf.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="'+filename+'"'})

def csv_response(result,filename):
    return _csv(result['rows'],result['columns'],filename)

PAIR_COLUMNS=['pair_no','reference_a','minutes_a','reference_b','minutes_b','diff_minutes','moisture_gap','thickness_gap','normalized_cost']
UNMATCHED_COLUMNS=['group','reference','moisture','thickness','candidate_count','reason']

def _published_pair_run(db,id,message):
    r=db.get(PairRun,id)
    if not r:raise HTTPException(404,'未找到配对对照任务')
    if r.state!='completed' or r.pairs is None or not r.result or not r.result.get('estimate'):raise HTTPException(409,message)
    return r

def pair_run_csv(db,id):
    r=_published_pair_run(db,id,'配对名单与区间未齐全，暂不可下载')
    return _csv(pair_rows(r.pairs,r.snapshot['records_a'],r.snapshot['records_b']),PAIR_COLUMNS,'pair-run-'+str(id)+'.csv')

def pair_unmatched_csv(db,id):
    r=_published_pair_run(db,id,'配对名单与区间未齐全，暂不可下载')
    return _csv(r.unmatched or [],UNMATCHED_COLUMNS,'pair-run-'+str(id)+'-unmatched.csv')

def run_csv(db,id):
    r=get_run(db,id)
    if r.state!='completed':raise HTTPException(409,'结果尚未完成')
    return csv_response(r.result,'run-'+str(id)+'.csv')

def note_csv(db,id):
    n=db.get(Note,id)
    if not n:raise HTTPException(404,'未找到说明')
    if n.state!='approved':raise HTTPException(403,'仅批准后的业务说明可导出')
    return csv_response(n.frozen_result,'approved-'+str(id)+'.csv')
