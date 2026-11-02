package com.newsproject.notificaciones.model;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** Artículo clasificado reciente (copia local de article.classified, últimos 7 días). */
public record RecentArticle(
        UUID articleId,
        String url,
        String title,
        String summary,
        String source,
        String sourceId,
        Instant publishedAt,
        Instant ingestedAt,
        String imageUrl,
        String category,
        List<String> tags) {
}
