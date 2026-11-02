-- Copia local de las preferencias (evento user.preferences.updated)
CREATE TABLE IF NOT EXISTS preferences (
    user_id               UUID PRIMARY KEY,
    categories            TEXT[]      NOT NULL DEFAULT '{}',
    keywords              TEXT[]      NOT NULL DEFAULT '{}',
    notifications_enabled BOOLEAN     NOT NULL DEFAULT TRUE,
    occurred_at           TIMESTAMPTZ NOT NULL,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Fuentes que el usuario apagó en su feed (docs/eventos.md, 3.5)
ALTER TABLE preferences ADD COLUMN IF NOT EXISTS disabled_sources TEXT[] NOT NULL DEFAULT '{}';

-- Alertas guardadas antes de enviarse por WebSocket
CREATE TABLE IF NOT EXISTS alerts (
    notification_id UUID PRIMARY KEY,
    user_id         UUID        NOT NULL,
    article_id      UUID        NOT NULL,
    title           TEXT        NOT NULL,
    summary         TEXT,
    source          TEXT,
    category        TEXT        NOT NULL,
    tags            TEXT[]      NOT NULL DEFAULT '{}',
    url             TEXT,
    image_url       TEXT,
    ingested_at     TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ NOT NULL,
    is_read         BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Idempotencia: el mismo articulo no genera dos alertas para el mismo usuario
    CONSTRAINT alerts_user_article_uk UNIQUE (user_id, article_id)
);
CREATE INDEX IF NOT EXISTS alerts_user_created_idx ON alerts (user_id, sent_at DESC);

-- Copia de los artículos clasificados recientes (últimos 7 días): con ella se rellena el
-- feed de un usuario al guardar sus preferencias aunque no lleguen noticias nuevas.
CREATE TABLE IF NOT EXISTS recent_articles (
    article_id   UUID PRIMARY KEY,
    url          TEXT,
    title        TEXT        NOT NULL,
    summary      TEXT,
    source       TEXT,
    source_id    TEXT,
    published_at TIMESTAMPTZ,
    ingested_at  TIMESTAMPTZ,
    image_url    TEXT,
    category     TEXT        NOT NULL,
    tags         TEXT[]      NOT NULL DEFAULT '{}',
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recent_articles_received_idx ON recent_articles (received_at);

-- Alerta creada por el relleno inicial (artículo anterior a las preferencias), no en vivo
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS backfill BOOLEAN NOT NULL DEFAULT FALSE;

-- Fuente de la alerta: permite borrar las no leídas de una fuente que el usuario apaga
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS source_id TEXT;
