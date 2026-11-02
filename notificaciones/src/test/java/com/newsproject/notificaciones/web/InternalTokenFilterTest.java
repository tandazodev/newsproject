package com.newsproject.notificaciones.web;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class InternalTokenFilterTest {

    private static final String TOKEN = "token-de-prueba";

    /** Ejecuta el filtro y devuelve la cadena: getRequest() != null si la petición pasó. */
    private static MockFilterChain run(String configured, String path, String sent, MockHttpServletResponse resp)
            throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", path);
        if (sent != null) {
            req.addHeader(InternalTokenFilter.HEADER, sent);
        }
        MockFilterChain chain = new MockFilterChain();
        new InternalTokenFilter(configured).doFilter(req, resp, chain);
        return chain;
    }

    @Test
    void variableVaciaNoExigeToken() throws Exception {
        MockHttpServletResponse resp = new MockHttpServletResponse();
        assertNotNull(run("", "/api/notifications", null, resp).getRequest());
        assertEquals(200, resp.getStatus());
    }

    @Test
    void tokenCorrectoPasa() throws Exception {
        MockHttpServletResponse resp = new MockHttpServletResponse();
        assertNotNull(run(TOKEN, "/api/notifications", TOKEN, resp).getRequest());
    }

    @Test
    void tokenIncorrectoOAusenteDa403() throws Exception {
        for (String sent : new String[] {"otro", "", null}) {
            MockHttpServletResponse resp = new MockHttpServletResponse();
            assertNull(run(TOKEN, "/api/notifications", sent, resp).getRequest());
            assertEquals(403, resp.getStatus());
        }
    }

    @Test
    void handshakeWebSocketTambienExigeToken() throws Exception {
        MockHttpServletResponse resp = new MockHttpServletResponse();
        assertNull(run(TOKEN, "/ws", null, resp).getRequest());
        assertEquals(403, resp.getStatus());
        assertNotNull(run(TOKEN, "/ws", TOKEN, new MockHttpServletResponse()).getRequest());
    }

    @Test
    void healthQuedaSinToken() throws Exception {
        MockHttpServletResponse resp = new MockHttpServletResponse();
        assertNotNull(run(TOKEN, "/health", null, resp).getRequest());
    }
}
