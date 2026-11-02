package com.newsproject.notificaciones.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Modo distribuido (docker-compose.distribuido.yml): el puerto del servicio queda publicado en la
 * red, así que con INTERNAL_TOKEN definido solo se aceptan peticiones que traigan el mismo valor en
 * X-Internal-Token (lo pone el gateway). Cubre la API REST y el handshake HTTP de /ws. Vacío (modo
 * de una PC) = sin cambios. /health queda libre para diagnosticar la red.
 */
@Component
public class InternalTokenFilter extends OncePerRequestFilter {

    static final String HEADER = "X-Internal-Token";

    private final byte[] token;

    public InternalTokenFilter(@Value("${INTERNAL_TOKEN:}") String token) {
        this.token = token == null ? new byte[0] : token.getBytes(StandardCharsets.UTF_8);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return token.length == 0 || "/health".equals(request.getRequestURI());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String sent = request.getHeader(HEADER);
        byte[] recibido = sent == null ? new byte[0] : sent.getBytes(StandardCharsets.UTF_8);
        // Comparación en tiempo constante
        if (!MessageDigest.isEqual(recibido, token)) {
            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            response.setCharacterEncoding(StandardCharsets.UTF_8.name());
            response.getWriter().write("{\"detail\": \"token interno inválido\"}");
            return;
        }
        chain.doFilter(request, response);
    }
}
