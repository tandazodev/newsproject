# database.py
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import settings

logger = logging.getLogger(__name__)

class Database:
    client: AsyncIOMotorClient = None
    db = None

db_manager = Database()

async def connect_to_mongo():
    """Establece conexión a MongoDB, crea índices y carga fuentes iniciales."""
    try:
        db_manager.client = AsyncIOMotorClient(settings.DATABASE_URL)
        db_manager.db = db_manager.client[settings.DATABASE_NAME]
        
        # Crear índices requeridos
        await db_manager.db.sources.create_index("url", unique=True)
        await db_manager.db.articles.create_index([("published", 1)])
        # _id natural ya está indexado, indexamos published para búsquedas de pendientes
        await db_manager.db.scrape_log.create_index([("source_id", 1), ("started_at", -1)])
        
        # Cargar fuentes iniciales si la colección está vacía
        sources_count = await db_manager.db.sources.count_documents({})
        if sources_count == 0:
            logger.info("Colección sources vacía. Cargando fuentes iniciales...")
            initial_sources = [
                {"name": "El Universo", "url": "https://www.eluniverso.com/arc/outboundfeeds/rss/?outputType=xml", "active": True},
                {"name": "Perfil", "url": "https://www.perfil.com/feed", "active": True},
                {"name": "BBC Mundo", "url": "https://feeds.bbci.co.uk/mundo/rss.xml", "active": True},
                {"name": "Crónica", "url": "https://www.cronica.com.ar/rss/general.xml", "active": True}
            ]
            await db_manager.db.sources.insert_many(initial_sources)
            logger.info("Fuentes iniciales cargadas exitosamente.")
            
    except Exception as e:
        logger.error(f"Error conectando a MongoDB: {str(e)}")
        raise e

async def close_mongo_connection():
    """Cierra la conexión a MongoDB"""
    if db_manager.client:
        db_manager.client.close()