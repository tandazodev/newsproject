// Feed en vivo. Responsable: Ariel.
// Tiempo real según docs/arquitectura.md, sección 6:
//   WS    /ws/notifications?user_id=<id>                     alertas nuevas (notification.new_article)
//   GET   /api/notifications?user_id=<id>                    historial (al entrar)
//   GET   /api/notifications?user_id=<id>&unread=true        pendientes (en cada (re)conexión)
//   PATCH /api/notifications/{id}/read                       al abrir una alerta
// Si el WebSocket se cae, se reconecta cada pocos segundos y recupera lo que
// llegó mientras tanto. El contador de no leídos vive en NotificacionesContext.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { get, patch } from "../api.js";
import Portada from "../components/Portada.jsx";
import { useNotificaciones } from "../context/NotificacionesContext.jsx";
import { getUserId } from "../user.js";

const RECONEXION_MS = 3000;
const PING_MS = 30000; // keep-alive: Notificaciones responde "pong"

// Lista oficial (docs/eventos.md, sección 4).
const CATEGORIAS = {
  politica: "Política",
  economia: "Economía",
  tecnologia: "Tecnología",
  deportes: "Deportes",
  salud: "Salud",
  cultura: "Cultura",
  internacional: "Internacional",
  otros: "Otros",
};

const formatoFecha = new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" });

function fecha(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : formatoFecha.format(d);
}

function duracion(ms) {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 60000)} min`;
}

// Latencia extremo a extremo (docs/arquitectura.md, sección 10): llegada a la pantalla − ingested_at.
// Solo tiene sentido para las alertas recibidas en vivo; las recuperadas por REST muestran
// en cambio cuánto tardó el sistema en generarlas (sent_at − ingested_at).
function latencias(alerta) {
  const ingested = Date.parse(alerta.ingested_at);
  return {
    enVivo: alerta.llegada != null ? alerta.llegada - ingested : null,
    sistema: Date.parse(alerta.sent_at) - ingested,
  };
}

function urlWebSocket(userId) {
  const protocolo = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocolo}//${window.location.host}/ws/notifications?user_id=${encodeURIComponent(userId)}`;
}

// Une alertas sin repetir (por notification_id); las más recientes primero.
function unir(actuales, nuevas) {
  const porId = new Map(actuales.map((a) => [a.notification_id, a]));
  for (const n of nuevas) {
    const previa = porId.get(n.notification_id);
    // La versión en vivo (con hora de llegada) gana; "leída" no se pierde al recargar pendientes
    porId.set(n.notification_id, previa
      ? { ...n, ...previa, read: previa.read || n.read }
      : n);
  }
  return [...porId.values()].sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at));
}

function EstadoConexion({ estado }) {
  const textos = {
    conectando: "Conectando…",
    conectado: "En vivo",
    reconectando: "Sin conexión · reintentando…",
  };
  return (
    <span className={`conexion conexion-${estado}`} role="status">
      <span className="conexion-punto" aria-hidden="true" />
      {textos[estado]}
    </span>
  );
}

function Latencia({ alerta }) {
  const { enVivo, sistema } = latencias(alerta);
  return enVivo != null ? (
    <span className="latencia" title="Llegada a la pantalla − ingested_at">
      Latencia: <strong>{duracion(enVivo)}</strong>
    </span>
  ) : (
    <span className="latencia" title="sent_at − ingested_at (recuperada al conectar)">
      Recuperada · procesada en {duracion(sistema)}
    </span>
  );
}

function Etiquetas({ tags }) {
  if (!tags?.length) return null;
  return (
    <ul className="feed-etiquetas">
      {tags.map((t) => <li key={t}>#{t}</li>)}
    </ul>
  );
}

function Detalle({ alerta, onVolver }) {
  return (
    <section className="feed-detalle">
      <button type="button" className="boton boton-secundario" onClick={onVolver}>← Volver al feed</button>
      <article className="tarjeta">
        <Portada article={alerta} />
        <p className="feed-datos">
          <span className="feed-categoria">{CATEGORIAS[alerta.category] ?? alerta.category}</span>
          {alerta.source && <span>{alerta.source}</span>}
          <time dateTime={alerta.sent_at}>{fecha(alerta.sent_at)}</time>
        </p>
        <h1>{alerta.title}</h1>
        {alerta.summary && <p>{alerta.summary}</p>}
        <Etiquetas tags={alerta.tags} />
        <p className="feed-datos"><Latencia alerta={alerta} /></p>
        {alerta.url && (
          <a className="boton" href={alerta.url} target="_blank" rel="noopener noreferrer">
            Leer en la fuente original ↗
          </a>
        )}
      </article>
    </section>
  );
}

function Alerta({ alerta, onAbrir }) {
  return (
    <li className={alerta.read ? "tarjeta alerta" : "tarjeta alerta alerta-nueva"}>
      <button type="button" className="alerta-boton" onClick={onAbrir}>
        <span className="alerta-portada"><Portada article={alerta} /></span>
        <span className="alerta-cuerpo">
          <span className="feed-datos">
            {!alerta.read && <span className="punto-nueva" aria-label="No leída" />}
            <span className="feed-categoria">{CATEGORIAS[alerta.category] ?? alerta.category}</span>
            {alerta.source && <span>{alerta.source}</span>}
            <time dateTime={alerta.sent_at}>{fecha(alerta.sent_at)}</time>
          </span>
          <span className="alerta-titulo">{alerta.title}</span>
          {alerta.summary && <span className="alerta-resumen">{alerta.summary}</span>}
          <span className="feed-datos"><Latencia alerta={alerta} /></span>
        </span>
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------
export default function Feed() {
  const userId = getUserId();
  const { setUnread } = useNotificaciones();
  const [alertas, setAlertas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);
  const [estado, setEstado] = useState("conectando");
  const [abierta, setAbierta] = useState(null); // notification_id en detalle
  const activo = useRef(true);

  const agregar = useCallback((nuevas) => setAlertas((actuales) => unir(actuales, nuevas)), []);

  const cargar = useCallback(async (soloPendientes) => {
    try {
      const lista = await get(
        `/notifications?user_id=${encodeURIComponent(userId)}${soloPendientes ? "&unread=true" : ""}`
      );
      if (activo.current) {
        agregar(lista.map((a) => ({ ...a, llegada: null })));
        setError(null);
      }
    } catch (e) {
      if (activo.current) {
        setError([502, 503, 504].includes(e.status)
          ? "El servicio de notificaciones no está disponible. Se reintentará al reconectar."
          : `No se pudieron cargar las alertas (${e.message}).`);
      }
    } finally {
      if (activo.current) setCargando(false);
    }
  }, [userId, agregar]);

  // Historial al entrar
  useEffect(() => {
    activo.current = true;
    cargar(false);
    return () => {
      activo.current = false;
    };
  }, [cargar]);

  // WebSocket con reconexión
  useEffect(() => {
    let ws = null;
    let temporizador = null;
    let ping = null;
    let cerrado = false;

    function conectar() {
      ws = new WebSocket(urlWebSocket(userId));
      ws.onopen = () => {
        setEstado("conectado");
        cargar(true); // lo que llegó mientras no había conexión
        ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), PING_MS);
      };
      ws.onmessage = (evento) => {
        let mensaje;
        try {
          mensaje = JSON.parse(evento.data);
        } catch {
          return; // "pong" u otro texto
        }
        if (mensaje?.type === "notification.new_article" && mensaje.data) {
          agregar([{ ...mensaje.data, read: false, llegada: Date.now() }]);
        }
      };
      ws.onclose = () => {
        clearInterval(ping);
        if (cerrado) return;
        setEstado("reconectando");
        temporizador = setTimeout(conectar, RECONEXION_MS);
      };
    }

    conectar();
    return () => {
      cerrado = true;
      clearTimeout(temporizador);
      clearInterval(ping);
      ws?.close();
    };
  }, [userId, cargar, agregar]);

  // Contador de no leídos del menú
  const noLeidas = alertas.filter((a) => !a.read).length;
  useEffect(() => {
    setUnread(noLeidas);
  }, [noLeidas, setUnread]);

  async function abrir(alerta) {
    setAbierta(alerta.notification_id);
    if (alerta.read) return;
    setAlertas((lista) => lista.map((a) => (a.notification_id === alerta.notification_id ? { ...a, read: true } : a)));
    try {
      await patch(`/notifications/${alerta.notification_id}/read`);
    } catch {
      // Si falla, se queda leída en pantalla; al recargar volverá a aparecer como pendiente
    }
  }

  const detalle = abierta && alertas.find((a) => a.notification_id === abierta);
  if (detalle) return <Detalle alerta={detalle} onVolver={() => setAbierta(null)} />;

  return (
    <section className="feed">
      <div className="feed-cabecera">
        <h1>Feed</h1>
        <EstadoConexion estado={estado} />
      </div>
      <p className="suave">
        {noLeidas > 0 ? `${noLeidas} sin leer. ` : ""}
        Las noticias que coinciden con tus <Link to="/preferencias">preferencias</Link> aparecen aquí al instante.
      </p>

      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {cargando && <p className="suave">Cargando alertas…</p>}
      {!cargando && alertas.length === 0 && !error && (
        <div className="tarjeta feed-vacio">
          <p>Aún no tienes alertas.</p>
          <p className="suave">
            Elige categorías o palabras clave en <Link to="/preferencias">Preferencias</Link> y trae noticias
            nuevas desde <Link to="/fuentes">Fuentes</Link>.
          </p>
        </div>
      )}

      <ul className="lista-alertas" aria-live="polite">
        {alertas.map((a) => (
          <Alerta key={a.notification_id} alerta={a} onAbrir={() => abrir(a)} />
        ))}
      </ul>
    </section>
  );
}
