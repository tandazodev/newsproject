# rabbitmq.py
import json
import logging
import asyncio
import uuid
import aio_pika
from .config import settings
from .database import db_manager
from .utils import utc_now_z

logger = logging.getLogger(__name__)

class RabbitMQClient:
    connection: aio_pika.RobustConnection = None
    channel: aio_pika.Channel = None
    exchange: aio_pika.Exchange = None

mq = RabbitMQClient()

async def connect_to_rabbitmq():
    """Establece conexión robusta a RabbitMQ y obtiene el exchange.

    El exchange lo crea rabbitmq-init (infra/rabbitmq/definitions.json); aquí solo se
    verifica que exista. Si falla, la excepción sube y main.with_retries reintenta.
    """
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    try:
        channel = await connection.channel()
        exchange = await channel.get_exchange(settings.EXCHANGE_NAME)
    except Exception as e:
        logger.error(f"Error conectando a RabbitMQ: {str(e)}")
        await connection.close()
        raise
    mq.connection, mq.channel, mq.exchange = connection, channel, exchange
    logger.info("Conectado a RabbitMQ exitosamente.")

async def close_rabbitmq_connection():
    if mq.connection and not mq.connection.is_closed:
        await mq.connection.close()

def build_event(payload: dict) -> dict:
    """Sobre común de docs/eventos.md (sección 2); routing key = event_type."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": settings.ROUTING_KEY,
        "occurred_at": utc_now_z(),
        "version": 1,
        "payload": payload,
    }

async def publish_event(payload: dict) -> bool:
    """Publica un evento article.ingested (con el sobre común) en RabbitMQ."""
    if not mq.exchange:
        logger.error("RabbitMQ no está inicializado.")
        return False
    try:
        event = build_event(payload)
        message = aio_pika.Message(
            body=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
            message_id=event["event_id"],
        )
        await mq.exchange.publish(message, routing_key=event["event_type"])
        return True
    except Exception as e:
        logger.error(f"Error publicando evento en RabbitMQ: {str(e)}")
        return False

async def retry_pending_articles():
    """
    Busca artículos marcados como published=False y reintenta su publicación.
    Esto garantiza resiliencia en caso de caídas previas de RabbitMQ.
    """
    try:
        cursor = db_manager.db.articles.find({"published": False})
        async for article in cursor:
            # Recrear payload sin el _id de mongo ni published
            payload = {
                "article_id": article.get("_id"),
                "url": article.get("normalized_url"),
                "title": article.get("title"),
                "body": article.get("body"),
                "source": article.get("source"),
                "source_id": article.get("source_id"),
                "published_at": article.get("published_at"),
                "image_url": article.get("image_url"),
                "hash": article.get("hash")
            }
            
            success = await publish_event(payload)
            if success:
                # Marcar como publicado
                await db_manager.db.articles.update_one(
                    {"_id": article["_id"]},
                    {"$set": {"published": True}}
                )
    except Exception as e:
        logger.error(f"Error en retry_pending_articles: {str(e)}")