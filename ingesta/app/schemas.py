# schemas.py
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List
from datetime import datetime

class SourceCreate(BaseModel):
    name: str = Field(..., description="Nombre del medio (ej. BBC Mundo)")
    url: HttpUrl = Field(..., description="URL del feed RSS")
    active: bool = True

class SourceResponse(SourceCreate):
    id: str
    
class ScrapeLogResponse(BaseModel):
    source_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    found: int
    new: int
    updated: int
    errors: int