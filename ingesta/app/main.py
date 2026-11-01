# main.py
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from pydantic import HttpUrl
from bson import ObjectId

from config import settings
from database import connect_to_mongo, close_mongo_connection, db_manager
from rabbitmq import connect_to_rabbitmq, close_rabbitmq_connection, mq
from scraper import scrape_source, run_periodic_scraping
from schemas import SourceCreate, SourceResponse, ScrapeLogResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Variables globales para tareas de fondo
background_tasks_refs = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Iniciar conexiones
    await connect_to_mongo()
    await connect_to_rabbitmq()
    
    # Iniciar el ciclo automático de 10 minutos
    task = asyncio.create_task(run_periodic_scraping())
    background_tasks_refs.add(task)
    task.add_done_callback(background_tasks_refs.discard)
    
    yield
    
    # Cerrar recursos
    for t in background_tasks_refs:
        t.cancel()
    await close_rabbitmq_connection()
    await close_mongo_connection()

app = FastAPI(title="Módulo Ingesta API", version="1.0.0", lifespan=lifespan)

@app.get("/api/sources", response_model=list[SourceResponse])
async def get_sources():
    """Obtiene la lista de todas las fuentes configuradas."""
    sources = []
    async for source in db_manager.db.sources.find():
        source["id"] = str(source["_id"])
        sources.append(source)
    return sources

@app.post("/api/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(source: SourceCreate):
    """Añade un nuevo feed RSS a las fuentes."""
    existing = await db_manager.db.sources.find_one({"url": str(source.url)})
    if existing:
        raise HTTPException(status_code=409, detail="La URL de esta fuente ya existe.")
    
    doc = source.model_dump()
    doc["url"] = str(doc["url"])
    result = await db_manager.db.sources.insert_one(doc)
    
    doc["id"] = str(result.inserted_id)
    return doc

@app.post("/api/sources/{id}/scrape", status_code=status.HTTP_202_ACCEPTED)
async def trigger_scrape(id: str, background_tasks: BackgroundTasks):
    """Dispara un scraping manual en segundo plano para una fuente específica."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="ID de fuente inválido")
        
    source = await db_manager.db.sources.find_one({"_id": ObjectId(id)})
    if not source:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
        
    background_tasks.add_task(scrape_source, id)
    return {"message": "Scraping iniciado en segundo plano."}

@app.get("/api/sources/{id}/log", response_model=list[ScrapeLogResponse])
async def get_scrape_logs(id: str):
    """Devuelve las últimas 20 ejecuciones de scraping para una fuente."""
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="ID inválido")
        
    logs = []
    cursor = db_manager.db.scrape_log.find({"source_id": id}).sort("started_at", -1).limit(20)
    async for log in cursor:
        logs.append(log)
    return logs

@app.get("/health")
async def health_check():
    """Verifica las conexiones vitales del contenedor (MongoDB y RabbitMQ)."""
    health = {"status": "ok", "mongo": "ok", "rabbitmq": "ok"}
    try:
        # Check Mongo
        await db_manager.client.admin.command('ping')
    except Exception:
        health["mongo"] = "error"
        health["status"] = "error"
        
    # Check RabbitMQ
    if not mq.connection or mq.connection.is_closed:
        health["rabbitmq"] = "error"
        health["status"] = "error"
        
    if health["status"] == "error":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=health)
        
    return health