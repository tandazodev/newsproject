package com.newsproject.notificaciones.service;

import com.newsproject.notificaciones.messaging.ArticleClassifiedEvent;
import com.newsproject.notificaciones.messaging.UserPreferencesUpdatedEvent;
import com.newsproject.notificaciones.model.RecentArticle;
import com.newsproject.notificaciones.model.StoredAlert;
import com.newsproject.notificaciones.model.UserPreferences;
import com.newsproject.notificaciones.repository.AlertRepository;
import com.newsproject.notificaciones.repository.PreferencesRepository;
import com.newsproject.notificaciones.repository.RecentArticleRepository;
import com.newsproject.notificaciones.util.StructuredLog;
import com.newsproject.notificaciones.websocket.NotificationMessage;
import com.newsproject.notificaciones.websocket.NotificationWebSocketHandler;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.amqp.AmqpRejectAndDontRequeueException;
import org.springframework.beans.factory.annotation.Value;
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

    /** Categorias validas (docs/eventos.md, seccion 4). */
    private static final Set<String> CATEGORIES = Set.of(
            "politica", "economia", "tecnologia", "deportes",
            "salud", "cultura", "internacional", "otros");

    /** Relleno inicial: cuántos artículos recientes se convierten en alertas y de qué ventana. */
    static final int BACKFILL_MAX = 20;
    private static final int MAX_UNREAD_SCAN = 10_000;
    private static final int BACKFILL_SCAN = 500;

    private final PreferencesRepository preferences;
    private final AlertRepository alerts;
    private final RecentArticleRepository recent;
    private final NotificationWebSocketHandler webSocket;

    /**
     * Ventana de retención (ALERTS_RETENTION_DAYS, 7 días): las alertas y los artículos recientes
     * más antiguos se borran (AlertCleanup); el relleno usa la misma ventana para no recrear lo borrado.
     */
    private final Duration recentWindow;

    public NotificationService(PreferencesRepository preferences, AlertRepository alerts,
                               RecentArticleRepository recent, NotificationWebSocketHandler webSocket,
                               @Value("${alerts.retention-days:7}") int retentionDays) {
        this.recentWindow = Duration.ofDays(retentionDays);
        this.preferences = preferences;
        this.alerts = alerts;
        this.recent = recent;
        this.webSocket = webSocket;
    }

    // ------------------------------------------------------------------
    // user.preferences.updated
    // ------------------------------------------------------------------
    public void handlePreferences(UserPreferencesUpdatedEvent event) {
        if (event == null || event.eventId() == null || event.occurredAt() == null || event.payload() == null) {
            throw invalid("user.preferences.updated incompleto (event_id, occurred_at o payload ausente)");
        }
        UserPreferencesUpdatedEvent.Payload p = event.payload();
        // Todos obligatorios (docs/eventos.md, 3.3): sin ellos el mensaje va directo a la .dlq
        List<String> missing = new ArrayList<>();
        if (p.userId() == null) missing.add("user_id");
        if (p.categories() == null) missing.add("categories");
        if (p.keywords() == null) missing.add("keywords");
        if (p.notificationsEnabled() == null) missing.add("notifications_enabled");
        if (!missing.isEmpty()) {
            throw invalid("user.preferences.updated sin campos obligatorios: " + String.join(", ", missing));
        }
        List<String> categories = clean(p.categories());
        List<String> keywords = clean(p.keywords());
        boolean enabled = p.notificationsEnabled();
        // Ids de fuente: se respetan tal cual (sin pasar a minúsculas), sin vacíos ni repetidos
        List<String> disabledSources = p.disabledSources() == null ? List.of()
                : p.disabledSources().stream().filter(s -> s != null && !s.isBlank()).map(String::trim)
                        .distinct().toList();

        boolean saved = preferences.upsert(p.userId(), categories, keywords, enabled, disabledSources,
                event.occurredAt());
        StructuredLog.log(saved ? "preferences.saved" : "preferences.stale_ignored",
                "event_id", event.eventId(), "user_id", p.userId(),
                "categories", categories.size(), "keywords", keywords.size(),
                "notifications_enabled", enabled, "disabled_sources", disabledSources.size());
        if (saved) {
            // Coincidencia por intereses (sin mirar notifications_enabled): apagar las notificaciones
            // no borra el feed; cambiar de intereses sí quita lo que ya no coincide.
            UserPreferences intereses = new UserPreferences(p.userId(), categories, keywords, true, disabledSources);
            pruneUnreadNotMatching(intereses, event);
            if (enabled) {
                backfill(intereses, event);
            }
        }
    }

    /**
     * Al cambiar las preferencias se borran las alertas NO leídas que ya no coinciden (categoría,
     * keyword o fuente apagada). Las leídas se conservan como historial hasta la retención.
     */
    private void pruneUnreadNotMatching(UserPreferences prefs, UserPreferencesUpdatedEvent event) {
        List<UUID> borrar = alerts.findByUser(prefs.userId(), true, MAX_UNREAD_SCAN).stream()
                .filter(a -> (a.sourceId() != null && prefs.disabledSources().contains(a.sourceId()))
                        || !PreferenceMatcher.matches(prefs, a.category(), a.title(), a.tags()))
                .map(StoredAlert::notificationId)
                .toList();
        int borradas = alerts.deleteAll(borrar);
        StructuredLog.log("preferences.pruned", "event_id", event.eventId(), "user_id", prefs.userId(),
                "unread_removed", borradas);
    }

    /**
     * Relleno inicial del feed: con las preferencias nuevas, asegura que el usuario tenga alerta
     * de las BACKFILL_MAX coincidencias más recientes (crea solo las que falten), así el feed se
     * construye aunque al scrapear no haya noticias nuevas. Idempotente: guardar las mismas
     * preferencias o reentregar el evento no crea nada nuevo (UNIQUE user_id, article_id).
     */
    private void backfill(UserPreferences prefs, UserPreferencesUpdatedEvent event) {
        Instant base = Instant.now().truncatedTo(ChronoUnit.MILLIS);
        int matched = 0;
        int created = 0;
        int delivered = 0;
        for (RecentArticle r : recent.findRecent(recentWindow, BACKFILL_SCAN)) {
            if (matched >= BACKFILL_MAX) {
                break;
            }
            if (r.sourceId() != null && prefs.disabledSources().contains(r.sourceId())) {
                continue;
            }
            if (!PreferenceMatcher.matches(prefs, r.category(), r.title(), r.tags())) {
                continue;
            }
            matched++;
            // sent_at decreciente: en el feed (ordenado por sent_at) quedan por fecha de publicación
            StoredAlert alert = new StoredAlert(
                    UUID.randomUUID(), prefs.userId(), r.articleId(), r.title(), r.summary(), r.source(),
                    r.category(), r.tags(), r.url(), r.imageUrl(), r.ingestedAt(),
                    base.minusMillis(matched), false, true, r.sourceId());
            if (!alerts.insertIfAbsent(alert)) {
                continue;   // ya tenía alerta de ese artículo
            }
            created++;
            delivered += webSocket.sendToUser(prefs.userId(), NotificationMessage.newArticle(alert)) > 0 ? 1 : 0;
        }
        StructuredLog.log("preferences.backfill", "event_id", event.eventId(), "user_id", prefs.userId(),
                "matched", matched, "alerts_created", created, "delivered_live", delivered);
    }

    // ------------------------------------------------------------------
    // article.classified
    // ------------------------------------------------------------------
    public void handleArticle(ArticleClassifiedEvent event) {
        if (event == null || event.eventId() == null || event.payload() == null) {
            throw invalid("article.classified incompleto (event_id o payload ausente)");
        }
        ArticleClassifiedEvent.Payload a = event.payload();
        // Campos obligatorios de docs/eventos.md, 3.2 (image_url es opcional)
        List<String> missing = new ArrayList<>();
        if (event.occurredAt() == null) missing.add("occurred_at");
        if (a.articleId() == null) missing.add("article_id");
        if (isBlank(a.url())) missing.add("url");
        if (isBlank(a.title())) missing.add("title");
        if (isBlank(a.summary())) missing.add("summary");
        if (isBlank(a.source())) missing.add("source");
        if (a.publishedAt() == null) missing.add("published_at");
        if (a.ingestedAt() == null) missing.add("ingested_at");
        if (isBlank(a.category())) missing.add("category");
        if (a.tags() == null) missing.add("tags");
        if (a.score() == null) missing.add("score");
        if (!missing.isEmpty()) {
            throw invalid("article.classified sin campos obligatorios: " + String.join(", ", missing));
        }
        if (!CATEGORIES.contains(a.category())) {
            throw invalid("article.classified con categoria no valida: " + a.category());
        }
        if (a.score() < 0 || a.score() > 1) {
            throw invalid("article.classified con score fuera de 0..1: " + a.score());
        }
        List<String> tags = a.tags();
        // Copia local para el relleno inicial del feed de usuarios nuevos o que cambian intereses
        recent.upsert(new RecentArticle(a.articleId(), a.url(), a.title(), a.summary(), a.source(),
                a.sourceId(), a.publishedAt(), a.ingestedAt(), a.imageUrl(), a.category(), tags));
        Instant ingestedAt = a.ingestedAt();

        int matched = 0;
        int sentCount = 0;
        int duplicates = 0;

        for (UserPreferences prefs : preferences.findEnabled()) {
            // Fuente apagada por el usuario: no hay alerta aunque coincida (docs/eventos.md, 3.5)
            if (a.sourceId() != null && prefs.disabledSources().contains(a.sourceId())) {
                continue;
            }
            if (!PreferenceMatcher.matches(prefs, a.category(), a.title(), tags)) {
                continue;
            }
            matched++;

            Instant sentAt = Instant.now().truncatedTo(ChronoUnit.MILLIS);
            StoredAlert alert = new StoredAlert(
                    UUID.randomUUID(), prefs.userId(), a.articleId(), a.title(), a.summary(),
                    a.source(), a.category(), tags, a.url(), a.imageUrl(), ingestedAt, sentAt, false, false,
                    a.sourceId());

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
