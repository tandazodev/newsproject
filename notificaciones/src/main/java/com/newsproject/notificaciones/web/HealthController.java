package com.newsproject.notificaciones.web;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Docker y el gateway lo usan como healthcheck: 200 solo si PostgreSQL y RabbitMQ responden. */
@RestController
public class HealthController {

    private final JdbcTemplate jdbc;
    private final RabbitTemplate rabbit;

    public HealthController(JdbcTemplate jdbc, RabbitTemplate rabbit) {
        this.jdbc = jdbc;
        this.rabbit = rabbit;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        boolean dbOk = false;
        boolean mqOk = false;
        try {
            dbOk = Integer.valueOf(1).equals(jdbc.queryForObject("SELECT 1", Integer.class));
        } catch (Exception ignored) {
            // db = error
        }
        try {
            mqOk = Boolean.TRUE.equals(rabbit.execute(channel -> channel.isOpen()));
        } catch (Exception ignored) {
            // rabbitmq = error
        }
        Map<String, String> body = new LinkedHashMap<>();
        body.put("status", dbOk && mqOk ? "ok" : "unavailable");
        body.put("service", "notificaciones");
        body.put("db", dbOk ? "ok" : "error");
        body.put("rabbitmq", mqOk ? "ok" : "error");
        return ResponseEntity.status(dbOk && mqOk ? 200 : 503).body(body);
    }
}
