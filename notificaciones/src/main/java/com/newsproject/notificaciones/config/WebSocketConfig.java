package com.newsproject.notificaciones.config;

import com.newsproject.notificaciones.websocket.NotificationWebSocketHandler;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final NotificationWebSocketHandler handler;

    public WebSocketConfig(NotificationWebSocketHandler handler) {
        this.handler = handler;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        // El gateway reenvia /ws/notifications?user_id=<id> a ws://notificaciones:8080/ws?user_id=<id>.
        // La autenticacion avanzada queda fuera del alcance (el usuario se identifica por su user_id).
        registry.addHandler(handler, "/ws", "/ws/notifications").setAllowedOrigins("*");
    }
}
