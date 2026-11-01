# schemas.py
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List
from datetime import datetime

class SourceCreate(BaseModel):
    name: str = Field(..., description="Nombre del medio (ej. BBC Mundo)")
    url: HttpUrl = Field(..., description="URL del feed RSS")
    active: bool = True

class ScrapeLogResponse(BaseModel):
    source_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    found: int
    new: int
    updated: int
    errors: int

class LastScrape(BaseModel):
    """Último estado de la fuente (docs/arquitectura.md, sección 7)."""
    status: str = Field(..., description='"ok" o "error"')
    started_at: datetime
    finished_at: Optional[datetime]
    found: int
    new: int
    updated: int
    errors: int

class SourceResponse(SourceCreate):
    id: str
    last_scrape: Optional[LastScrape] = None