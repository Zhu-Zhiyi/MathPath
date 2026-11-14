"""A model proposes a theorem memory; it never certifies mathematical truth."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class MemoryCandidate(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    name:str=Field(min_length=1,max_length=180)
    category:Literal["common","nonstandard"]
    statement:str=Field(min_length=1,max_length=16000)
    assumptions:list[str]=Field(max_length=24)
    uncertainties:list[str]=Field(max_length=16)
    statement_complete:bool
