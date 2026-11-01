package com.newsproject.notificaciones.util;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Una linea JSON por evento, igual que los servicios Python
 * ({"ts", "service", "stage", ...}) para poder seguir un articulo de punta a punta.
 */
public final class StructuredLog {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String SERVICE = "notificaciones";

    private StructuredLog() {
    }

    /** @param fields pares clave, valor: log("alert.sent", "event_id", id, "user_id", u) */
    public static void log(String stage, Object... fields) {
        Map<String, Object> line = new LinkedHashMap<>();
        line.put("ts", Instant.now().truncatedTo(ChronoUnit.MILLIS).toString());
        line.put("service", SERVICE);
        line.put("stage", stage);
        for (int i = 0; i + 1 < fields.length; i += 2) {
            Object value = fields[i + 1];
            if (value instanceof UUID || value instanceof Instant) {
                value = value.toString();
            }
            line.put(String.valueOf(fields[i]), value);
        }
        try {
            System.out.println(MAPPER.writeValueAsString(line));
        } catch (Exception e) {
            System.out.println("{\"service\":\"" + SERVICE + "\",\"stage\":\"" + stage + "\"}");
        }
    }
}
