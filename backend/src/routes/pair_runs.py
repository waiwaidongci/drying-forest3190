from fastapi import APIRouter,Depends
from ..config.database import db_session
from ..schemas.pair_run import PairRunInput
from ..services.auth import current_user,writer
from ..services.export import pair_run_csv,pair_unmatched_csv
from ..controllers.pair_runs import PairRunsController as C
router=APIRouter()
@router.get('/pair-runs')
def pair_runs(db=Depends(db_session),u=Depends(current_user)):return C.list(db)
@router.post('/pair-runs')
def create(data:PairRunInput,db=Depends(db_session),u=Depends(writer)):return C.create(db,u,data)
@router.get('/pair-runs/{id}')
def detail(id:int,db=Depends(db_session),u=Depends(current_user)):return C.get(db,id)
@router.post('/pair-runs/{id}/retry')
def retry(id:int,db=Depends(db_session),u=Depends(writer)):return C.retry(db,u,id)
@router.get('/pair-runs/{id}/export')
def export(id:int,db=Depends(db_session),u=Depends(current_user)):return pair_run_csv(db,id)
@router.get('/pair-runs/{id}/export-unmatched')
def export_unmatched(id:int,db=Depends(db_session),u=Depends(current_user)):return pair_unmatched_csv(db,id)
