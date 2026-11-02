package com.newsproject.notificaciones.websocket;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.newsproject.notificaciones.util.StructuredLog;
import java.io.IOException;
import java.net.URI;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * Sesiones WebSocket agrupadas por usuario: ws://.../ws?user_id=<uuid>.
 * Una alerta solo se envia a las sesiones abiertas de su destinatario.
 */
@Component
public class NotificationWebSocketHandler extends TextWebSocketHandler {

    private static final String ATTR_USER = "user_id";
    private static final String ATTR_SAFE = "safe_session";

    private final Map<UUID, Set<WebSocketSession>> sessionsByUser = new ConcurrentHashMap<>();
    private final ObjectMapper objectMapper;

    public NotificationWebSocketHandler(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        UUID userId = extractUserId(session.getUri());
        if (userId == null) {
            session.close(CloseStatus.POLICY_VIOLATION.withReason("user_id requerido (UUID)"));
            return;
        }
        // WebSocketSession no es thread-safe: el decorador serializa los envios
        WebSocketSession safe = new ConcurrentWebSocketSessionDecorator(session, 5_000, 64 * 1024);
        session.getAttributes().put(ATTR_USER, userId);
        session.getAttributes().put(ATTR_SAFE, safe);
        Set<WebSocketSession> userSessions =
                sessionsByUser.computeIfAbsent(userId, k -> ConcurrentHashMap.newKeySet());
        userSessions.add(safe);
        StructuredLog.log("ws.open", "user_id", userId, "session", session.getId(),
                "sessions_for_user", userSessions.size());
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) throws IOException {
        // Keep-alive opcional del cliente
        if ("ping".equalsIgnoreCase(message.getPayload().trim())) {
            WebSocketSession safe = (WebSocketSession) session.getAttributes().get(ATTR_SAFE);
            if (safe != null && safe.isOpen()) {
                safe.sendMessage(new TextMessage("pong"));
            }
        }
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        remove(session);
    }

    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) {
        StructuredLog.log("ws.transport_error", "session", session.getId(), "error", exception.getMessage());
        remove(session);
    }

    /**
     * Envia el mensaje a las sesiones abiertas del usuario.
     *
     * @return cuantas sesiones lo recibieron (0 si el usuario no esta conectado: la alerta
     *         ya esta guardada y la recuperara con GET /api/notifications?unread=true)
     */
    public int sendToUser(UUID userId, Object message) {
        Set<WebSocketSession> sessions = sessionsByUser.get(userId);
        if (sessions == null || sessions.isEmpty()) {
            return 0;
        }
        final String json;
        try {
            json = objectMapper.writeValueAsString(message);
        } catch (JsonProcessingException e) {
            StructuredLog.log("ws.serialize_error", "user_id", userId, "error", e.getMessage());
            return 0;
        }
        TextMessage text = new TextMessage(json);
        int delivered = 0;
        for (WebSocketSession s : sessions) {
            try {
                if (s.isOpen()) {
                    s.sendMessage(text);
                    delivered++;
                }
            } catch (IOException | RuntimeException e) {
                StructuredLog.log("ws.send_error", "user_id", userId, "session", s.getId(),
                        "error", e.getMessage());
            }
        }
        return delivered;
    }

    /** Sesiones WebSocket abiertas (para el panel del administrador). */
    public int openSessions() {
        return sessionsByUser.values().stream().mapToInt(Set::size).sum();
    }

    /** Usuarios con al menos una sesión abierta. */
    public int connectedUsers() {
        return sessionsByUser.size();
    }

    private void remove(WebSocketSession session) {
        UUID userId = (UUID) session.getAttributes().get(ATTR_USER);
        WebSocketSession safe = (WebSocketSession) session.getAttributes().get(ATTR_SAFE);
        if (userId == null || safe == null) {
            return;
        }
        sessionsByUser.computeIfPresent(userId, (k, set) -> {
            set.remove(safe);
            return set.isEmpty() ? null : set;
        });
        StructuredLog.log("ws.closed", "user_id", userId, "session", session.getId());
    }

    private static UUID extractUserId(URI uri) {
        if (uri == null) {
            return null;
        }
        String value = UriComponentsBuilder.fromUri(uri).build().getQueryParams().getFirst(ATTR_USER);
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return UUID.fromString(value);
        } catch (IllegalArgumentException e) {
            return null;
        }
    }
}
