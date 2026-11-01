package com.newsproject.notificaciones.repository;

import com.newsproject.notificaciones.model.UserPreferences;
import java.sql.Array;
import java.sql.PreparedStatement;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class PreferencesRepository {

    private final JdbcTemplate jdbc;

    public PreferencesRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * Reemplaza por completo las preferencias del usuario (no es un diff).
     * Un evento con occurred_at mas antiguo que el ya guardado se ignora.
     *
     * @return true si se guardo; false si el evento era mas antiguo (descartado)
     */
    public boolean upsert(UUID userId, List<String> categories, List<String> keywords,
                          boolean enabled, Instant occurredAt) {
        String sql = """
                INSERT INTO preferences
                    (user_id, categories, keywords, notifications_enabled, occurred_at, updated_at)
                VALUES (?, ?, ?, ?, ?, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    categories = EXCLUDED.categories,
                    keywords = EXCLUDED.keywords,
                    notifications_enabled = EXCLUDED.notifications_enabled,
                    occurred_at = EXCLUDED.occurred_at,
                    updated_at = now()
                WHERE preferences.occurred_at <= EXCLUDED.occurred_at
                """;
        int rows = jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(sql);
            ps.setObject(1, userId);
            ps.setArray(2, con.createArrayOf("text", categories.toArray()));
            ps.setArray(3, con.createArrayOf("text", keywords.toArray()));
            ps.setBoolean(4, enabled);
            ps.setObject(5, OffsetDateTime.ofInstant(occurredAt, ZoneOffset.UTC));
            return ps;
        });
        return rows > 0;
    }

    /** Usuarios con las notificaciones activadas. */
    public List<UserPreferences> findEnabled() {
        return jdbc.query(
                "SELECT user_id, categories, keywords, notifications_enabled "
                        + "FROM preferences WHERE notifications_enabled",
                (rs, i) -> new UserPreferences(
                        rs.getObject("user_id", UUID.class),
                        toList(rs.getArray("categories")),
                        toList(rs.getArray("keywords")),
                        rs.getBoolean("notifications_enabled")));
    }

    static List<String> toList(Array array) throws java.sql.SQLException {
        if (array == null) {
            return List.of();
        }
        return Arrays.asList((String[]) array.getArray());
    }
}
