# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Configuraciones globales del módulo Ingesta"""
    # Conexiones a servicios
    DATABASE_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "newsproject_db"
    RABBITMQ_URL: str = "amqp://guest:guest@localhost/"
    # Modo distribuido: token que debe traer X-Internal-Token (lo pone el gateway). Vacío = sin control
    INTERNAL_TOKEN: str = ""
    
    # Configuración del Scraping
    SCRAPING_INTERVAL_MINUTES: int = 5  # los feeds se refrescan cada ~5 min (cache-control: max-age=300)
    HTTP_TIMEOUT_SECONDS: int = 10
    USER_AGENT: str = "newsproject-unl/1.0 (proyecto academico)"
    
    # Nombres de colas y exchanges
    EXCHANGE_NAME: str = "newsproject.events"
    ROUTING_KEY: str = "article.ingested"

    class Config:
        env_file = ".env"

settings = Settings()