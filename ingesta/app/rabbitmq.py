# rabbitmq.py
import json
import logging
import asyncio
import aio_pika
from config import settings
from database import db_manager

logger = logging.getLogger(__name__)

class RabbitMQClient:
    connection: aio_pika.RobustConnection = None
    channel: aio_pika.Channel = None
    exchange: aio_pika.Exchange = None

mq = RabbitMQClient()

async def connect_to_rabbitmq():
    """Establece conexión robusta a RabbitMQ y declara el exchange."""
    try:
        mq.connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        mq.channel = await mq.connection.channel()
        mq.exchange = await mq.channel.declare_exchange(
            settings.EXCHANGE_NAME, 
            aio_pika.ExchangeType.TOPIC,
            durable=True
        )
        logger.info("Conectado a RabbitMQ exitosamente.")
    except Exception as e:
        logger.error(f"Error conectando a RabbitMQ: {str(e)}")

async def close_rabbitmq_connection():
    if mq.connection and not mq.connection.is_closed:
        await mq.connection.close()

async def publish_event(payload: dict) -> bool:
    """Publica un evento en RabbitMQ."""
    if not mq.exchange:
        logger.error("RabbitMQ no está inicializado.")
        return False
    try:
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json"
        )
        await mq.exchange.publish(message, routing_key=settings.ROUTING_KEY)
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
                "normalized_url": article.get("normalized_url"),
                "article_id": article.get("_id"),
                "title": article.get("title"),
                "body": article.get("body"),
                "source": article.get("source"),
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