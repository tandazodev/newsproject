package com.newsproject.notificaciones;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Notificaciones (responsable: Ariel).
 *
 * Consume article.classified y user.preferences.updated, cruza cada articulo con las
 * preferencias de los usuarios, guarda la alerta en PostgreSQL y la emite por WebSocket
 * (docs/arquitectura.md, secciones 6 y 7).
 */
@SpringBootApplication
@EnableScheduling   // limpieza periódica de alertas antiguas (service/AlertCleanup)
public class NotificacionesApplication {

    public static void main(String[] args) {
        SpringApplication.run(NotificacionesApplication.class, args);
    }
}
