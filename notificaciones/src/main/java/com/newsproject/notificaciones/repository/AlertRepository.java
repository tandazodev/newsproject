package com.newsproject.notificaciones.repository;

import com.newsproject.notificaciones.model.StoredAlert;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class AlertRepository {

    private static final String COLUMNS = """
            notification_id, user_id, article_id, title, summary, source, category, tags,
            url, image_url, ingested_at, sent_at, is_read
            """;

    private static final RowMapper<StoredAlert> MAPPER = AlertRepository::map;

    private final JdbcTemplate jdbc;

    public AlertRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * Guarda la alerta. La restriccion UNIQUE (user_id, article_id) vuelve idempotente el
     * proceso: si el articulo ya genero una alerta para ese usuario, no hace nada.
     *
     * @return true si la alerta es nueva; false si ya existia
     */
    public boolean insertIfAbsent(StoredAlert a) {
        String sql = """
                INSERT INTO alerts (notification_id, user_id, article_id, title, summary, source,
                    category, tags, url, image_url, ingested_at, sent_at, is_read)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE)
                ON CONFLICT (user_id, article_id) DO NOTHING
                """;
        int rows = jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(sql);
            ps.setObject(1, a.notificationId());
            ps.setObject(2, a.userId());
            ps.setObject(3, a.articleId());
            ps.setString(4, a.title());
            ps.setString(5, a.summary());
            ps.setString(6, a.source());
            ps.setString(7, a.category());
            ps.setArray(8, con.createArrayOf("text", a.tags().toArray()));
            ps.setString(9, a.url());
            ps.setString(10, a.imageUrl());
            ps.setObject(11, a.ingestedAt() == null ? null : OffsetDateTime.ofInstant(a.ingestedAt(), ZoneOffset.UTC));
            ps.setObject(12, OffsetDateTime.ofInstant(a.sentAt(), ZoneOffset.UTC));
            return ps;
        });
        return rows > 0;
    }

    /** Alertas del usuario, las mas recientes primero. */
    public List<StoredAlert> findByUser(UUID userId, boolean unreadOnly, int limit) {
        String sql = "SELECT " + COLUMNS + " FROM alerts WHERE user_id = ? "
                + (unreadOnly ? "AND NOT is_read " : "")
                + "ORDER BY sent_at DESC LIMIT ?";
        return jdbc.query(sql, MAPPER, userId, limit);
    }

    public Optional<StoredAlert> findById(UUID notificationId) {
        List<StoredAlert> rows = jdbc.query(
                "SELECT " + COLUMNS + " FROM alerts WHERE notification_id = ?", MAPPER, notificationId);
        return rows.stream().findFirst();
    }

    /** Marca la alerta como leida (idempotente) y la devuelve; vacio si no existe. */
    public Optional<StoredAlert> markRead(UUID notificationId) {
        jdbc.update("UPDATE alerts SET is_read = TRUE WHERE notification_id = ?", notificationId);
        return findById(notificationId);
    }

    private static StoredAlert map(ResultSet rs, int i) throws SQLException {
        return new StoredAlert(
                rs.getObject("notification_id", UUID.class),
                rs.getObject("user_id", UUID.class),
                rs.getObject("article_id", UUID.class),
                rs.getString("title"),
                rs.getString("summary"),
                rs.getString("source"),
                rs.getString("category"),
                PreferencesRepository.toList(rs.getArray("tags")),
                rs.getString("url"),
                rs.getString("image_url"),
                toInstant(rs.getObject("ingested_at", OffsetDateTime.class)),
                toInstant(rs.getObject("sent_at", OffsetDateTime.class)),
                rs.getBoolean("is_read"));
    }

    private static Instant toInstant(OffsetDateTime value) {
        return value == null ? null : value.toInstant();
    }
}
