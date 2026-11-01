package com.newsproject.notificaciones.service;

import com.newsproject.notificaciones.model.UserPreferences;
import java.text.Normalizer;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Regla de coincidencia (docs/arquitectura.md, seccion 6): hay coincidencia si las
 * notificaciones estan activadas y la categoria del articulo esta en categories, o alguna
 * keyword aparece en los tags o en el titulo.
 *
 * Las comparaciones ignoran mayusculas y tildes, y tratan "-" como espacio
 * (el tag "inteligencia-artificial" coincide con la keyword "inteligencia artificial").
 * Las keywords se buscan como palabra completa: "ai" no coincide con "mail".
 */
public final class PreferenceMatcher {

    private PreferenceMatcher() {
    }

    public static boolean matches(UserPreferences prefs, String category, String title, List<String> tags) {
        if (!prefs.notificationsEnabled()) {
            return false;
        }
        if (category != null) {
            String cat = normalize(category);
            for (String c : prefs.categories()) {
                if (normalize(c).equals(cat)) {
                    return true;
                }
            }
        }
        String normTitle = normalize(title);
        List<String> normTags = (tags == null ? List.<String>of() : tags).stream()
                .map(PreferenceMatcher::normalize)
                .toList();
        for (String keyword : prefs.keywords()) {
            String k = normalize(keyword);
            if (k.isEmpty()) {
                continue;
            }
            Pattern word = Pattern.compile(
                    "(?<![\\p{L}\\p{N}])" + Pattern.quote(k) + "(?![\\p{L}\\p{N}])");
            if (word.matcher(normTitle).find()) {
                return true;
            }
            for (String tag : normTags) {
                if (word.matcher(tag).find()) {
                    return true;
                }
            }
        }
        return false;
    }

    static String normalize(String text) {
        if (text == null) {
            return "";
        }
        String s = Normalizer.normalize(text, Normalizer.Form.NFD)
                .replaceAll("\\p{M}+", "")
                .toLowerCase(Locale.ROOT)
                .replaceAll("[-_]+", " ")
                .replaceAll("\\s+", " ")
                .trim();
        return s;
    }
}
