package com.newsproject.notificaciones.messaging;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** Evento user.preferences.updated (ver docs/eventos.md, seccion 3.3). */
public record UserPreferencesUpdatedEvent(
        UUID eventId,
        String eventType,
        Instant occurredAt,
        int version,
        Payload payload) {

    public record Payload(
            UUID userId,
            List<String> categories,
            List<String> keywords,
            Boolean notificationsEnabled,
            List<String> disabledSources) {   // opcional: ausente equivale a []
    }
}
