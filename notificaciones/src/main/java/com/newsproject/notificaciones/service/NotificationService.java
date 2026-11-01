package com.newsproject.notificaciones.service;

import com.newsproject.notificaciones.messaging.ArticleClassifiedEvent;
import com.newsproject.notificaciones.messaging.UserPreferencesUpdatedEvent;
import com.newsproject.notificaciones.model.StoredAlert;
import com.newsproject.notificaciones.model.UserPreferences;
import com.newsproject.notificaciones.repository.AlertRepository;
import com.newsproject.notificaciones.repository.PreferencesRepository;
import com.newsproject.notificaciones.util.StructuredLog;
import com.newsproject.notificaciones.websocket.NotificationMessage;
import com.newsproject.notificaciones.websocket.NotificationWebSocketHandler;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.UUID;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.stereotype.Service;

/**
 * Logica de Notificaciones:
 *  - user.preferences.updated -> actualiza la copia local de preferencias.
 *  - article.classified -> cruza con las preferencias, guarda la alerta y LUEGO la envia
 *    por WebSocket (asi ninguna alerta se pierde si el usuario no esta conectado).
 *
 * Los errores transitorios (BD caida) se propagan: RabbitMQ reentrega y, tras 3 entregas,
 * manda el mensaje a la .dlq. Los mensajes invalidos se rechazan sin reencolar.
 */
@Service
public class NotificationService {

    private final PreferencesRepository preferences;
    private final AlertRepository alerts;
    private final NotificationWebSocketHandler webSocket;

    public NotificationService(PreferencesRepository preferences, AlertRepository alerts,
                               NotificationWebSocketHandler webSocket) {
        this.preferences = preferences;
        this.alerts = alerts;
        this.webSocket = webSocket;
    }

    // ------------------------------------------------------------------
    // user.preferences.updated
    // ------------------------------------------------------------------
    public void handlePreferences(UserPreferencesUpdatedEvent event) {
        if (event == null || event.eventId() == null || event.occurredAt() == null
                || event.payload() == null || event.payload().userId() == null) {
            throw invalid("user.preferences.updated incompleto (event_id, occurred_at o user_id ausente)");
        }
        UserPreferencesUpdatedEvent.Payload p = event.payload();
        List<String> categories = clean(p.categories());
        List<String> keywords = clean(p.keywords());
        boolean enabled = p.notificationsEnabled() == null || p.notificationsEnabled();

        boolean saved = preferences.upsert(p.userId(), categories, keywords, enabled, event.occurredAt());
        StructuredLog.log(saved ? "preferences.saved" : "preferences.stale_ignored",
                "event_id", event.eventId(), "user_id", p.userId(),
                "categories", categories.size(), "keywords", keywords.size(),
                "notifications_enabled", enabled);
    }

    // ------------------------------------------------------------------
    // article.classified
    // ------------------------------------------------------------------
    public void handleArticle(ArticleClassifiedEvent event) {
        if (event == null || event.eventId() == null || event.payload() == null) {
            throw invalid("article.classified incompleto (event_id o payload ausente)");
        }
        ArticleClassifiedEvent.Payload a = event.payload();
        if (a.articleId() == null || isBlank(a.title()) || isBlank(a.category())) {
            throw invalid("article.classified incompleto (article_id, title o category ausente)");
        }
        List<String> tags = a.tags() == null ? List.of() : a.tags();
        Instant ingestedAt = a.ingestedAt() != null ? a.ingestedAt() : event.occurredAt();

        int matched = 0;
        int sentCount = 0;
        int duplicates = 0;

        for (UserPreferences prefs : preferences.findEnabled()) {
            if (!PreferenceMatcher.matches(prefs, a.category(), a.title(), tags)) {
                continue;
            }
            matched++;

            Instant sentAt = Instant.now().truncatedTo(ChronoUnit.MILLIS);
            StoredAlert alert = new StoredAlert(
                    UUID.randomUUID(), prefs.userId(), a.articleId(), a.title(), a.summary(),
                    a.source(), a.category(), tags, a.url(), a.imageUrl(), ingestedAt, sentAt, false);

            // 1) guardar; 2) enviar. Si ya existia (mensaje repetido) no se reenvia.
            if (!alerts.insertIfAbsent(alert)) {
                duplicates++;
                continue;
            }
            int delivered = webSocket.sendToUser(prefs.userId(), NotificationMessage.newArticle(alert));
            sentCount++;

            StructuredLog.log("alert.sent",
                    "event_id", event.eventId(), "article_id", a.articleId(),
                    "user_id", prefs.userId(), "notification_id", alert.notificationId(),
                    "sessions", delivered,
                    "ingested_at", ingestedAt, "sent_at", sentAt,
                    "latency_ms", Duration.between(ingestedAt, sentAt).toMillis());
        }

        StructuredLog.log("article.processed",
                "event_id", event.eventId(), "article_id", a.articleId(),
                "category", a.category(), "matched", matched, "alerts_created", sentCount,
                "duplicates", duplicates,
                "classification_latency_ms",
                event.occurredAt() == null ? null : Duration.between(ingestedAt, event.occurredAt()).toMillis());
    }

    // ------------------------------------------------------------------
    private static AmqpRejectAndDontRequeueException invalid(String reason) {
        StructuredLog.log("message.invalid", "reason", reason);
        return new AmqpRejectAndDontRequeueException(reason);
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    /** Normaliza (minusculas, sin vacios ni repetidos, conservando el orden). */
    private static List<String> clean(List<String> values) {
        if (values == null) {
            return List.of();
        }
        LinkedHashSet<String> out = new LinkedHashSet<>();
        for (String v : values) {
            if (v != null && !v.isBlank()) {
                out.add(v.trim().toLowerCase());
            }
        }
        return List.copyOf(out);
    }
}
