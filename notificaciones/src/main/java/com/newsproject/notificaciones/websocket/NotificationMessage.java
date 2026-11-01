package com.newsproject.notificaciones.websocket;

import com.newsproject.notificaciones.model.StoredAlert;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Mensaje enviado al cliente (docs/arquitectura.md, seccion 6):
 * {"type": "notification.new_article", "data": {...}} en snake_case.
 */
public record NotificationMessage(String type, Data data) {

    public static final String NEW_ARTICLE = "notification.new_article";

    public record Data(
            UUID notificationId,
            UUID articleId,
            String title,
            String summary,
            String source,
            String category,
            List<String> tags,
            String url,
            String imageUrl,
            Instant ingestedAt,
            Instant sentAt) {
    }

    public static NotificationMessage newArticle(StoredAlert a) {
        return new NotificationMessage(NEW_ARTICLE, new Data(
                a.notificationId(), a.articleId(), a.title(), a.summary(), a.source(),
                a.category(), a.tags(), a.url(), a.imageUrl(), a.ingestedAt(), a.sentAt()));
    }
}
