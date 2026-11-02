# scraper.py
import httpx
import feedparser
import logging
from datetime import datetime, timezone
from .config import settings
from .database import db_manager
from .utils import (normalize_url, entry_title_body, entry_date, entry_image, utc_now_z,
                    generate_article_id, generate_hash)
from .rabbitmq import retry_pending_articles

logger = logging.getLogger(__name__)

async def fetch_feed(url: str) -> bytes:
    """Descarga el contenido del feed RSS usando httpx de manera asíncrona."""
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        headers = {"User-Agent": settings.USER_AGENT}
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        # Bytes sin decodificar, como el recolector: feedparser respeta la
        # codificación que declara el propio XML.
        return response.content

async def scrape_source(source_id: str):
    """
    Ejecuta el scraping para una fuente en particular: 
    Descarga, parsea, deduplica, inserta/actualiza en DB y levanta bandera de republicación.
    """
    from bson import ObjectId
    
    source = await db_manager.db.sources.find_one({"_id": ObjectId(source_id)})
    if not source or not source.get("active"):
        return

    log_entry = {
        "source_id": str(source_id),
        "started_at": datetime.now(timezone.utc),
        "finished_at": None,
        "found": 0,
        "new": 0,
        "updated": 0,
        "errors": 0
    }
    
    try:
        raw_xml = await fetch_feed(source["url"])
        feed = feedparser.parse(raw_xml)
        
        log_entry["found"] = len(feed.entries)
        
        for entry in feed.entries:
            try:
                raw_url = getattr(entry, "link", "")
                if not raw_url:
                    continue
                    
                norm_url = normalize_url(raw_url)
                article_id = generate_article_id(norm_url)
                # title + ". " + body es el mismo texto que entry_text del recolector
                title, body = entry_title_body(entry)
                if not title or not body:
                    # title y body son obligatorios en article.ingested: no se publica
                    continue
                img_url = entry_image(entry)
                content_hash = generate_hash(title, body)

                # published_at en ISO 8601 UTC con Z; si el feed no trae fecha, la hora actual
                pub_date = entry_date(entry) or utc_now_z()

                # Armar documento para DB
                article_doc = {
                    "_id": article_id,
                    "normalized_url": norm_url,
                    "title": title,
                    "body": body,
                    "source": source["name"],
                    # id de la fuente: permite a cada usuario apagarla en su feed (eventos.md 3.5)
                    "source_id": str(source["_id"]),
                    "published_at": pub_date,
                    "image_url": img_url,
                    "hash": content_hash,
                    "published": False  # Se actualizará a True tras enviar a RabbitMQ
                }
                
                # Lógica estricta de Deduplicación
                existing = await db_manager.db.articles.find_one({"_id": article_id})
                
                if not existing:
                    # Artículo Nuevo
                    await db_manager.db.articles.insert_one(article_doc)
                    log_entry["new"] += 1
                else:
                    # Existe, comparar Hash
                    if existing.get("hash") != content_hash:
                        # Modificado
                        await db_manager.db.articles.replace_one({"_id": article_id}, article_doc)
                        log_entry["updated"] += 1
                    # Si el hash es igual, no se hace nada
                    
            except Exception as e:
                logger.error(f"Error procesando entry del feed {source['name']}: {str(e)}")
                log_entry["errors"] += 1
                
    except Exception as e:
        logger.error(f"Error general scrapeando {source['name']} ({source['url']}): {str(e)}")
        log_entry["errors"] += 1
    finally:
        # Registrar finalización del scrape log
        log_entry["finished_at"] = datetime.now(timezone.utc)
        await db_manager.db.scrape_log.insert_one(log_entry)
        
        # Una vez guardados en DB los pendientes (nuevos o actualizados),
        # ejecutar el procesador de envíos a RabbitMQ
        await retry_pending_articles()

async def run_periodic_scraping():
    """Ciclo automático que se ejecuta cada N minutos en segundo plano."""
    import asyncio
    while True:
        try:
            logger.info("Iniciando ciclo automático de scraping...")
            # Extraer solo fuentes activas
            cursor = db_manager.db.sources.find({"active": True})
            sources = await cursor.to_list(length=None)
            
            for source in sources:
                await scrape_source(str(source["_id"]))
                
            logger.info("Ciclo de scraping finalizado.")
        except Exception as e:
            logger.error(f"Error en el ciclo automático: {str(e)}")
            
        # Esperar hasta el siguiente ciclo (SCRAPING_INTERVAL_MINUTES)
        await asyncio.sleep(settings.SCRAPING_INTERVAL_MINUTES * 60)