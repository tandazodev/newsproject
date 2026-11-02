# database.py
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

logger = logging.getLogger(__name__)

class Database:
    client: AsyncIOMotorClient = None
    db = None

db_manager = Database()

async def connect_to_mongo():
    """Establece conexión a MongoDB, crea índices y carga fuentes iniciales."""
    # serverSelectionTimeoutMS corto: si MongoDB aún no arranca, falla rápido y
    # main.with_retries vuelve a intentar con espera creciente.
    # tz_aware: las fechas vuelven como UTC con zona y se serializan con Z.
    client = AsyncIOMotorClient(settings.DATABASE_URL, serverSelectionTimeoutMS=2000, tz_aware=True)
    try:
        # La BD es la de DATABASE_URL (.../ingesta); DATABASE_NAME solo si la URL no la trae.
        db = client.get_default_database(default=settings.DATABASE_NAME)

        # Crear índices requeridos
        await db.sources.create_index("url", unique=True)
        await db.articles.create_index([("published", 1)])
        # _id natural ya está indexado, indexamos published para búsquedas de pendientes
        await db.scrape_log.create_index([("source_id", 1), ("started_at", -1)])

        # Cargar fuentes iniciales si la colección está vacía
        sources_count = await db.sources.count_documents({})
        if sources_count == 0:
            logger.info("Colección sources vacía. Cargando fuentes iniciales...")
            initial_sources = [
                {"name": "El Universo", "url": "https://www.eluniverso.com/arc/outboundfeeds/rss/?outputType=xml", "active": True},
                {"name": "Perfil", "url": "https://www.perfil.com/feed", "active": True},
                {"name": "BBC Mundo", "url": "https://feeds.bbci.co.uk/mundo/rss.xml", "active": True},
                {"name": "El País", "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada", "active": True}
            ]
            await db.sources.insert_many(initial_sources)
            logger.info("Fuentes iniciales cargadas exitosamente.")

    except Exception as e:
        logger.error(f"Error conectando a MongoDB: {str(e)}")
        client.close()
        raise e

    # Solo se publica cuando la conexión está lista (los endpoints responden 503 antes).
    db_manager.client = client
    db_manager.db = db

async def close_mongo_connection():
    """Cierra la conexión a MongoDB"""
    if db_manager.client:
        db_manager.client.close()