package com.newsproject.notificaciones.model;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Alerta guardada. Tambien es el cuerpo de GET /api/notifications
 * (se serializa en snake_case: notification_id, user_id, article_id, ...).
 */
public record StoredAlert(
        UUID notificationId,
        UUID userId,
        UUID articleId,
        String title,
        String summary,
        String source,
        String category,
        List<String> tags,
        String url,
        String imageUrl,
        Instant ingestedAt,
        Instant sentAt,
        boolean read) {
}
