package com.newsproject.notificaciones.service;

import com.newsproject.notificaciones.repository.AlertRepository;
import com.newsproject.notificaciones.repository.RecentArticleRepository;
import com.newsproject.notificaciones.util.StructuredLog;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Retención (docs/arquitectura.md, sección 6): cada hora borra las alertas y los artículos
 * recientes con más de ALERTS_RETENTION_DAYS días (7 por defecto), para que no se acumulen.
 * Las noticias antiguas siguen disponibles en Búsqueda.
 */
@Component
public class AlertCleanup {

    private final AlertRepository alerts;
    private final RecentArticleRepository recent;
    private final Duration retention;

    public AlertCleanup(AlertRepository alerts, RecentArticleRepository recent,
                        @Value("${alerts.retention-days:7}") int retentionDays) {
        this.alerts = alerts;
        this.recent = recent;
        this.retention = Duration.ofDays(retentionDays);
    }

    @Scheduled(initialDelayString = "${alerts.cleanup-initial-delay-ms:60000}",
               fixedDelayString = "${alerts.cleanup-interval-ms:3600000}")
    public void limpiar() {
        try {
            int alertas = alerts.deleteOlderThan(retention);
            int articulos = recent.prune(retention);
            StructuredLog.log("cleanup.done", "retention_days", retention.toDays(),
                    "alerts_removed", alertas, "recent_articles_removed", articulos);
        } catch (RuntimeException e) {
            // BD caída: se reintenta en la próxima ejecución
            StructuredLog.log("cleanup.failed", "error", e.getMessage());
        }
    }
}
