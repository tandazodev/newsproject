package com.newsproject.notificaciones.repository;

import com.newsproject.notificaciones.model.RecentArticle;
import java.sql.PreparedStatement;
import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Copia local de los artículos clasificados recientes. Notificaciones ya recibe todos los
 * article.classified por su cola: guardarlos le permite rellenar el feed de un usuario al
 * cambiar sus preferencias sin llamar a otro servicio (docs/arquitectura.md, sección 6).
 */
@Repository
public class RecentArticleRepository {

    private final JdbcTemplate jdbc;

    public RecentArticleRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Guarda o actualiza el artículo (idempotente por article_id). */
    public void upsert(RecentArticle a) {
        String sql = """
                INSERT INTO recent_articles (article_id, url, title, summary, source, source_id,
                    published_at, ingested_at, image_url, category, tags, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
                ON CONFLICT (article_id) DO UPDATE SET
                    url = EXCLUDED.url, title = EXCLUDED.title, summary = EXCLUDED.summary,
                    source = EXCLUDED.source, source_id = EXCLUDED.source_id,
                    published_at = EXCLUDED.published_at, ingested_at = EXCLUDED.ingested_at,
                    image_url = EXCLUDED.image_url, category = EXCLUDED.category,
                    tags = EXCLUDED.tags, received_at = now()
                """;
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(sql);
            ps.setObject(1, a.articleId());
            ps.setString(2, a.url());
            ps.setString(3, a.title());
            ps.setString(4, a.summary());
            ps.setString(5, a.source());
            ps.setString(6, a.sourceId());
            ps.setObject(7, toOffset(a.publishedAt()));
            ps.setObject(8, toOffset(a.ingestedAt()));
            ps.setString(9, a.imageUrl());
            ps.setString(10, a.category());
            ps.setArray(11, con.createArrayOf("text", a.tags().toArray()));
            return ps;
        });
    }

    /** Borra los artículos recibidos hace más de `keep`. */
    public int prune(Duration keep) {
        return jdbc.update("DELETE FROM recent_articles WHERE received_at < ?",
                toOffset(Instant.now().minus(keep)));
    }

    /** Artículos recibidos dentro de `window`, los más recientes (por publicación) primero. */
    public List<RecentArticle> findRecent(Duration window, int limit) {
        return jdbc.query("""
                SELECT article_id, url, title, summary, source, source_id, published_at,
                       ingested_at, image_url, category, tags
                FROM recent_articles
                WHERE received_at >= ?
                ORDER BY published_at DESC NULLS LAST
                LIMIT ?
                """,
                (rs, i) -> new RecentArticle(
                        rs.getObject("article_id", UUID.class),
                        rs.getString("url"),
                        rs.getString("title"),
                        rs.getString("summary"),
                        rs.getString("source"),
                        rs.getString("source_id"),
                        toInstant(rs.getObject("published_at", OffsetDateTime.class)),
                        toInstant(rs.getObject("ingested_at", OffsetDateTime.class)),
                        rs.getString("image_url"),
                        rs.getString("category"),
                        PreferencesRepository.toList(rs.getArray("tags"))),
                toOffset(Instant.now().minus(window)), limit);
    }

    private static OffsetDateTime toOffset(Instant value) {
        return value == null ? null : OffsetDateTime.ofInstant(value, ZoneOffset.UTC);
    }

    private static Instant toInstant(OffsetDateTime value) {
        return value == null ? null : value.toInstant();
    }
}
