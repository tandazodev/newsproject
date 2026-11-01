package com.newsproject.notificaciones.model;

import java.util.List;
import java.util.UUID;

/** Copia local de las preferencias de un usuario. */
public record UserPreferences(
        UUID userId,
        List<String> categories,
        List<String> keywords,
        boolean notificationsEnabled) {
}
