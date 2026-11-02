package com.newsproject.notificaciones.web;

import com.newsproject.notificaciones.websocket.NotificationWebSocketHandler;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Formato común de /health (docs/arquitectura.md, sección 7). Docker y el gateway lo usan como
 * healthcheck: 200 solo si PostgreSQL y RabbitMQ responden.
 */
@RestController
public class HealthController {

    private final JdbcTemplate jdbc;
    private final RabbitTemplate rabbit;
    private final NotificationWebSocketHandler webSocket;

    public HealthController(JdbcTemplate jdbc, RabbitTemplate rabbit, NotificationWebSocketHandler webSocket) {
        this.jdbc = jdbc;
        this.rabbit = rabbit;
        this.webSocket = webSocket;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        boolean dbOk = false;
        Long latency = null;
        boolean mqOk = false;
        Map<String, Object> details = new LinkedHashMap<>();
        try {
            long t0 = System.nanoTime();
            dbOk = Integer.valueOf(1).equals(jdbc.queryForObject("SELECT 1", Integer.class));
            latency = Math.round((System.nanoTime() - t0) / 1_000_000.0);
            details.put("users_with_preferences", jdbc.queryForObject("SELECT count(*) FROM preferences", Long.class));
            details.put("alerts", jdbc.queryForObject("SELECT count(*) FROM alerts", Long.class));
            details.put("recent_articles", jdbc.queryForObject("SELECT count(*) FROM recent_articles", Long.class));
        } catch (Exception ignored) {
            // db = error
        }
        try {
            mqOk = Boolean.TRUE.equals(rabbit.execute(channel -> channel.isOpen()));
        } catch (Exception ignored) {
            // rabbitmq = error
        }
        details.put("websocket_sessions", webSocket.openSessions());
        details.put("connected_users", webSocket.connectedUsers());

        Map<String, Object> db = new LinkedHashMap<>();
        db.put("status", dbOk ? "ok" : "error");
        db.put("engine", "postgresql");
        db.put("latency_ms", latency);
        Map<String, Object> checks = new LinkedHashMap<>();
        checks.put("db", db);
        checks.put("rabbitmq", Map.of("status", mqOk ? "ok" : "error"));

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", dbOk && mqOk ? "ok" : "unavailable");
        body.put("service", "notificaciones");
        body.put("checks", checks);
        body.put("details", details);
        return ResponseEntity.status(dbOk && mqOk ? 200 : 503).body(body);
    }
}
