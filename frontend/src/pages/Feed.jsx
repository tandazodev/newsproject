// Feed en vivo. Responsable: Ariel.
// Bandeja en dos paneles: a la izquierda las pestañas «Nuevas · Leídas» con una
// lista compacta que tiene su propio scroll; a la derecha el detalle de lo seleccionado. La
// página mide una pantalla y no crece. En móvil se ve una sola columna (lista o detalle).
// Tiempo real según docs/arquitectura.md, sección 6:
//   WS    /ws/notifications?token=<jwt>                      alertas nuevas (notification.new_article)
//   GET   /api/notifications?user_id=<id>                    historial (al entrar)
//   GET   /api/notifications?user_id=<id>&unread=true        pendientes (en cada (re)conexión)
//   PATCH /api/notifications/{id}/read                       al abrir una alerta
// Al guardar preferencias, Notificaciones crea las alertas de las noticias recientes que ya
// coincidían (relleno inicial, backfill): el feed nunca empieza vacío. Lo más antiguo está en Buscar.
// Si el WebSocket se cae, se reconecta cada pocos segundos y recupera lo que llegó mientras tanto.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { get, patch } from "../api.js";
import Portada from "../components/Portada.jsx";
import { useNotificaciones } from "../context/NotificacionesContext.jsx";
import { clearUser, getToken, getUserId } from "../user.js";

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
const formatoCorto = new Intl.DateTimeFormat("es-EC", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function fecha(iso, formato = formatoFecha) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : formato.format(d);
}

function duracion(ms) {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 60000)} min`;
}

// Latencia extremo a extremo (docs/arquitectura.md, sección 10): llegada a la pantalla − ingested_at.
// Solo para alertas recibidas en vivo; las recuperadas por REST muestran sent_at − ingested_at y las
// del relleno inicial (backfill) no tienen latencia: ya estaban publicadas.
function textoLatencia(alerta) {
  if (alerta.backfill) return { corto: "publicada", largo: "Ya publicada", titulo: "Ya estaba publicada cuando elegiste tus intereses" };
  const ingested = Date.parse(alerta.ingested_at);
  if (alerta.llegada != null) {
    const ms = alerta.llegada - ingested;
    return { corto: duracion(ms), largo: `Latencia: ${duracion(ms)}`, titulo: "Llegada a la pantalla − ingested_at" };
  }
  const ms = Date.parse(alerta.sent_at) - ingested;
  return { corto: duracion(ms), largo: `Recuperada · procesada en ${duracion(ms)}`, titulo: "sent_at − ingested_at" };
}

function urlWebSocket(token) {
  // El usuario sale del token, que valida el gateway (docs/arquitectura.md, 7.1)
  const protocolo = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocolo}//${window.location.host}/ws/notifications?token=${encodeURIComponent(token)}`;
}

// Une alertas sin repetir (por notification_id); las más recientes primero.
function unir(actuales, nuevas) {
  const porId = new Map(actuales.map((a) => [a.notification_id, a]));
  for (const n of nuevas) {
    const previa = porId.get(n.notification_id);
    // La versión en vivo (con hora de llegada) gana; "leída" no se pierde al recargar pendientes
    porId.set(n.notification_id, previa ? { ...n, ...previa, read: previa.read || n.read } : n);
  }
  return [...porId.values()].sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at));
}

function EstadoConexion({ estado }) {
  const textos = { conectando: "Conectando…", conectado: "En vivo", reconectando: "Sin conexión · reintentando…" };
  return (
    <span className={`conexion conexion-${estado}`} role="status">
      <span className="conexion-punto" aria-hidden="true" />
      {textos[estado]}
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

// ---------------------------------------------------------------------------
// Panel izquierdo: fila compacta
function Fila({ item, seleccionada, onElegir }) {
  const esAlerta = item.notification_id != null;
  const nueva = esAlerta && !item.read;
  const lat = esAlerta ? textoLatencia(item) : null;
  const cuando = esAlerta && !item.backfill ? item.sent_at : item.published_at ?? item.sent_at;
  return (
    <li>
      <button type="button" className={`fila${seleccionada ? " fila-activa" : ""}${nueva ? " fila-nueva" : ""}`}
              onClick={onElegir} aria-current={seleccionada ? "true" : undefined}>
        <span className="fila-punto" aria-label={nueva ? "No leída" : undefined} />
        <span className="fila-cuerpo">
          <span className="fila-titulo">{item.title}</span>
          <span className="fila-datos">
            <span className="feed-categoria">{CATEGORIAS[item.category] ?? item.category}</span>
            {item.source && <span>{item.source}</span>}
            {cuando && <time dateTime={cuando}>{fecha(cuando, formatoCorto)}</time>}
          </span>
        </span>
        {lat && <span className="fila-latencia" title={lat.titulo}>{lat.corto}</span>}
      </button>
    </li>
  );
}

// Panel derecho: detalle
function Detalle({ item, onVolver }) {
  if (!item) {
    return (
      <div className="detalle-vacio suave">
        <p>Elige una noticia de la lista para verla aquí.</p>
      </div>
    );
  }
  const esAlerta = item.notification_id != null;
  const lat = esAlerta ? textoLatencia(item) : null;
  return (
    <article className="detalle">
      <button type="button" className="boton boton-secundario detalle-volver" onClick={onVolver}>← Volver</button>
      <Portada article={item} />
      <p className="feed-datos">
        <span className="feed-categoria">{CATEGORIAS[item.category] ?? item.category}</span>
        {item.source && <span>{item.source}</span>}
        {item.published_at && <time dateTime={item.published_at}>{fecha(item.published_at)}</time>}
        {lat && <span className="latencia" title={lat.titulo}>{lat.largo}</span>}
      </p>
      <h2 className="detalle-titulo">{item.title}</h2>
      {item.summary && <p className="detalle-resumen">{item.summary}</p>}
      <Etiquetas tags={item.tags} />
      {item.url && (
        <a className="boton" href={item.url} target="_blank" rel="noopener noreferrer">
          Leer en la fuente original ↗
        </a>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
export default function Feed() {
  const userId = getUserId();
  const navigate = useNavigate();
  const { setUnread } = useNotificaciones();
  const [alertas, setAlertas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);
  const [estado, setEstado] = useState("conectando");
  const [pestana, setPestana] = useState("nuevas");
  const [seleccion, setSeleccion] = useState(null); // notification_id
  const [abiertoEnMovil, setAbiertoEnMovil] = useState(false);
  // Alertas leídas en esta visita a «Nuevas»: siguen en la lista hasta cambiar de pestaña
  const [leidasAhora, setLeidasAhora] = useState(() => new Set());
  const activo = useRef(true);

  const agregar = useCallback((nuevas) => setAlertas((actuales) => unir(actuales, nuevas)), []);

  const cargar = useCallback(async (soloPendientes) => {
    try {
      const lista = await get(`/notifications?user_id=${encodeURIComponent(userId)}${soloPendientes ? "&unread=true" : ""}`);
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
      const token = getToken();
      if (!token) {
        navigate("/login?vencida=1", { replace: true });
        return;
      }
      ws = new WebSocket(urlWebSocket(token));
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
      ws.onclose = (evento) => {
        clearInterval(ping);
        if (cerrado) return;
        if (evento.code === 1008) {
          // Token vencido o inválido: no tiene sentido reintentar
          clearUser();
          navigate("/login?vencida=1", { replace: true });
          return;
        }
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
  }, [userId, cargar, agregar, navigate]);

  // Contador de no leídos del menú
  const noLeidas = alertas.filter((a) => !a.read).length;
  useEffect(() => {
    setUnread(noLeidas);
  }, [noLeidas, setUnread]);

  // Listas de cada pestaña
  const listas = {
    nuevas: alertas.filter((a) => !a.read || leidasAhora.has(a.notification_id)),
    leidas: alertas.filter((a) => a.read),
  };
  const lista = listas[pestana];
  const claveDe = (item) => item.notification_id;
  const elegido = lista.find((i) => claveDe(i) === seleccion) ?? null;

  // En escritorio, si no hay nada elegido se muestra lo primero de la lista
  const mostrado = elegido ?? lista[0] ?? null;

  // Elegir una alerta la marca como leída (PATCH); sigue visible en «Nuevas» hasta cambiar de
  // pestaña. La que se muestra por defecto (la primera) no cuenta como leída hasta elegirla.
  const mostradoId = mostrado && claveDe(mostrado);
  const visible = elegido != null;
  useEffect(() => {
    if (!visible || mostrado.notification_id == null || mostrado.read) return;
    const id = mostrado.notification_id;
    setLeidasAhora((s) => new Set(s).add(id));
    setAlertas((l) => l.map((a) => (a.notification_id === id ? { ...a, read: true } : a)));
    patch(`/notifications/${id}/read`).catch(() => {
      // Si falla, queda leída en pantalla; al recargar volverá a aparecer como pendiente
    });
  }, [mostradoId, visible]); // eslint-disable-line react-hooks/exhaustive-deps

  function cambiarPestana(nueva) {
    setPestana(nueva);
    setSeleccion(null);
    setAbiertoEnMovil(false);
    setLeidasAhora(new Set());
  }

  function elegir(item) {
    setSeleccion(claveDe(item));
    setAbiertoEnMovil(true);
  }

  const pestanas = [
    ["nuevas", `Nuevas${noLeidas ? ` (${noLeidas})` : ""}`],
    ["leidas", "Leídas"],
  ];
  const vacios = {
    nuevas: "No tienes noticias nuevas. Te avisaremos aquí en cuanto llegue una que coincida con tus intereses.",
    leidas: "Aún no has leído ninguna alerta.",
  };

  return (
    <section className={`feed bandeja${abiertoEnMovil && mostrado ? " bandeja-detalle-abierto" : ""}`}>
      <div className="feed-cabecera">
        <h1>Feed</h1>
        <EstadoConexion estado={estado} />
      </div>
      <p className="suave feed-ayuda">
        Noticias de tus <Link to="/preferencias">preferencias</Link>; las nuevas llegan al instante.
      </p>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}

      <div className="bandeja-paneles">
        <div className="bandeja-lista">
          <div className="pestanas bandeja-pestanas" role="tablist">
            {pestanas.map(([clave, texto]) => (
              <button key={clave} type="button" role="tab" aria-selected={pestana === clave}
                      className={pestana === clave ? "pestana activa" : "pestana"} onClick={() => cambiarPestana(clave)}>
                {texto}
              </button>
            ))}
          </div>
          {cargando ? (
            <p className="suave bandeja-vacia">Cargando alertas…</p>
          ) : lista.length === 0 ? (
            <p className="suave bandeja-vacia">{vacios[pestana]}</p>
          ) : (
            <ul className="filas" aria-live={pestana === "nuevas" ? "polite" : undefined}>
              {lista.map((item) => (
                <Fila key={claveDe(item)} item={item} seleccionada={mostrado && claveDe(mostrado) === claveDe(item)}
                      onElegir={() => elegir(item)} />
              ))}
            </ul>
          )}
        </div>
        <div className="bandeja-detalle">
          <Detalle item={mostrado} onVolver={() => setAbiertoEnMovil(false)} />
        </div>
      </div>
    </section>
  );
}
