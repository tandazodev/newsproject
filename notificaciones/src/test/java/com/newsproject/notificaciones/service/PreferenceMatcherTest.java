package com.newsproject.notificaciones.service;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.newsproject.notificaciones.model.UserPreferences;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class PreferenceMatcherTest {

    private static UserPreferences prefs(List<String> cats, List<String> keys, boolean enabled) {
        return new UserPreferences(UUID.randomUUID(), cats, keys, enabled);
    }

    @Test
    void coincidePorCategoria() {
        assertTrue(PreferenceMatcher.matches(prefs(List.of("tecnologia"), List.of(), true),
                "tecnologia", "Titulo", List.of()));
    }

    @Test
    void coincidePorKeywordEnTitulo() {
        assertTrue(PreferenceMatcher.matches(prefs(List.of(), List.of("ecuador"), true),
                "deportes", "Ecuador gana el partido", List.of()));
    }

    @Test
    void coincidePorKeywordEnTagConGuiones() {
        assertTrue(PreferenceMatcher.matches(prefs(List.of(), List.of("inteligencia artificial"), true),
                "tecnologia", "Otro titulo", List.of("inteligencia-artificial")));
    }

    @Test
    void ignoraTildesYMayusculas() {
        assertTrue(PreferenceMatcher.matches(prefs(List.of(), List.of("economia"), true),
                "politica", "La ECONOMÍA crece", List.of()));
    }

    @Test
    void keywordEsPalabraCompleta() {
        assertFalse(PreferenceMatcher.matches(prefs(List.of(), List.of("ai"), true),
                "tecnologia", "Nuevo mail masivo", List.of()));
    }

    @Test
    void sinNotificacionesNoCoincide() {
        assertFalse(PreferenceMatcher.matches(prefs(List.of("tecnologia"), List.of(), false),
                "tecnologia", "Titulo", List.of()));
    }

    @Test
    void sinCoincidenciaDevuelveFalse() {
        assertFalse(PreferenceMatcher.matches(prefs(List.of("salud"), List.of("rabbitmq"), true),
                "deportes", "Final del torneo", List.of("futbol")));
    }
}
