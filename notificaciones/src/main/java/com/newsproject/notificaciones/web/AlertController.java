package com.newsproject.notificaciones.web;

import com.newsproject.notificaciones.model.StoredAlert;
import com.newsproject.notificaciones.repository.AlertRepository;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** REST de alertas (docs/arquitectura.md, seccion 7). */
@RestController
@RequestMapping("/api/notifications")
public class AlertController {

    private static final int MAX_RESULTS = 100;

    private final AlertRepository alerts;

    public AlertController(AlertRepository alerts) {
        this.alerts = alerts;
    }

    /** Alertas guardadas del usuario; con unread=true solo las no leidas (recuperacion al reconectar). */
    @GetMapping
    public List<StoredAlert> list(@RequestParam("user_id") String userId,
                                  @RequestParam(name = "unread", defaultValue = "false") boolean unread) {
        return alerts.findByUser(parseUuid(userId, "user_id"), unread, MAX_RESULTS);
    }

    /** Marca una alerta como leida. */
    @PatchMapping("/{id}/read")
    public StoredAlert markRead(@PathVariable("id") String id) {
        return alerts.markRead(parseUuid(id, "id"))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "notificacion no encontrada"));
    }

    private static UUID parseUuid(String value, String field) {
        try {
            return UUID.fromString(value);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, field + " debe ser un UUID");
        }
    }
}
