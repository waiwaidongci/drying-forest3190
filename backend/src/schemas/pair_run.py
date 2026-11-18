from pydantic import BaseModel,Field
class PairRunInput(BaseModel):
    name:str=Field(min_length=2,max_length=160)
    source_a_id:int
    source_b_id:int
    label_a:str=Field(default='A组',max_length=80)
    label_b:str=Field(default='B组',max_length=80)
    tolerance_humidity:float
    tolerance_thickness:float
