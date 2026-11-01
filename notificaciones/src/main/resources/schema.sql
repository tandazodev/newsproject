-- Copia local de las preferencias (evento user.preferences.updated)
CREATE TABLE IF NOT EXISTS preferences (
    user_id               UUID PRIMARY KEY,
    categories            TEXT[]      NOT NULL DEFAULT '{}',
    keywords              TEXT[]      NOT NULL DEFAULT '{}',
    notifications_enabled BOOLEAN     NOT NULL DEFAULT TRUE,
    occurred_at           TIMESTAMPTZ NOT NULL,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
