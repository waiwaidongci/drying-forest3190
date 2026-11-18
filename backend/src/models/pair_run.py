from sqlalchemy import Column,Integer,String,Text,JSON,ForeignKey
from ..config.database import Base
from ..config.settings import CONFIG
class PairRun(Base):
    __tablename__=CONFIG['pair_table']
    id=Column(Integer,primary_key=True)
    name=Column(String(160),nullable=False)
    source_a_id=Column(Integer,ForeignKey(CONFIG['source_table']+'.id'),nullable=False)
    source_b_id=Column(Integer,ForeignKey(CONFIG['source_table']+'.id'),nullable=False)
    label_a=Column(String(80),nullable=False,default='')
    label_b=Column(String(80),nullable=False,default='')
    tolerance_humidity=Column(String(40),nullable=False)
    tolerance_thickness=Column(String(40),nullable=False)
    state=Column(String(20),default='queued')
    snapshot=Column(JSON,nullable=False)
    pairs=Column(JSON,nullable=True)
    unmatched=Column(JSON,nullable=True)
    result=Column(JSON,nullable=True)
    error=Column(Text,default='')
    created_at=Column(String(40),nullable=False)
    updated_at=Column(String(40),nullable=False)
    published_at=Column(String(40),nullable=True)
