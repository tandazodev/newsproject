// Panel del administrador: estado de cada microservicio agrupado con su base de datos y sus
// colas, más la infraestructura (gateway, RabbitMQ, frontend). Usa GET /api/admin/status
// (solo rol admin, docs/arquitectura.md 7.1) y se refresca solo cada 10 s.
import { useCallback, useEffect, useState } from "react";
import { get } from "../api.js";

const REFRESCO_MS = 10000;
const ESTADOS = { ok: "OK", degraded: "Con problemas", down: "Caído" };
const MOTORES = { mongodb: "MongoDB", postgresql: "PostgreSQL" };

function Punto({ estado }) {
  return <span className={`punto punto-${estado}`} aria-hidden="true" />;
}

function Etiqueta({ estado }) {
  return (
    <span className={`estado-svc estado-svc-${estado}`}>
      <Punto estado={estado} />
      {ESTADOS[estado] ?? estado}
    </span>
  );
}

// Fila "componente · estado · dato" dentro de una tarjeta
function Fila({ nombre, ok, texto }) {
  const estado = ok == null ? "down" : ok ? "ok" : "degraded";
  return (
    <div className="svc-fila">
      <span className="svc-componente"><Punto estado={estado} />{nombre}</span>
      <span className="svc-dato">{texto}</span>
    </div>
  );
}

function detallesDe(s) {
  const d = s.details ?? {};
  switch (s.service) {
    case "ingesta":
      return [
        ["Fuentes", d.sources != null ? `${d.sources}${d.sources_with_errors ? ` · ${d.sources_with_errors} con error` : ""}` : "—"],
        ["Artículos", d.articles ?? "—"],
        ["Revisión automática", d.scraping_interval_minutes ? `cada ${d.scraping_interval_minutes} min` : "—"],
      ];
    case "clasificacion":
      return [
        ["Modelo", d.model === "loaded" ? `v${d.model_version ?? "?"} · ${d.algorithm ?? ""}` : "sin modelo"],
        ["F1 macro", d.f1_macro != null ? d.f1_macro.toFixed(3) : "—"],
        ["Umbral (otros)", d.min_score ?? "—"],
      ];
    case "busqueda":
      return [["Artículos indexados", d.articles_indexed ?? "—"]];
    case "usuarios":
      return [["Usuarios", d.users != null ? `${d.users} (${d.admins} admin)` : "—"]];
    case "notificaciones":
      return [
        ["WebSocket", d.websocket_sessions != null ? `${d.websocket_sessions} sesiones · ${d.connected_users} usuarios` : "—"],
        ["Alertas guardadas", d.alerts ?? "—"],
        ["Artículos recientes", d.recent_articles ?? "—"],
      ];
    default:
      return [];
  }
}

function Tarjeta({ s }) {
  const caido = !s.api.reachable;
  return (
    <article className={`tarjeta svc svc-${s.status}`}>
      <header className="svc-cabecera">
        <h2 className="tarjeta-titulo">{s.label}</h2>
        <Etiqueta estado={s.status} />
      </header>
      <Fila nombre="API" ok={caido ? null : s.api.http_status === 200}
            texto={caido ? "no responde" : `${s.api.http_status} · ${s.api.latency_ms} ms`} />
      <Fila nombre={MOTORES[s.db?.engine] ?? "Base de datos"} ok={caido ? null : s.db?.status === "ok"}
            texto={caido ? "desconocida" : s.db?.status === "ok" ? `conectada · ${s.db.latency_ms} ms` : "sin conexión"} />
      <Fila nombre="RabbitMQ" ok={caido ? null : s.rabbitmq?.status === "ok"}
            texto={caido ? "desconocido" : s.rabbitmq?.status === "ok" ? "conectado" : "sin conexión"} />
      {s.queues.map((q) => (
        <Fila key={q.name} nombre={`Cola ${q.name.split(".")[1]}`}
              ok={q.consumers == null ? null : q.consumers > 0 && !q.dlq.messages}
              texto={q.consumers == null ? "sin datos"
                : `${q.messages} msj · ${q.consumers} cons.${q.dlq.messages ? ` · DLQ ${q.dlq.messages}` : ""}`} />
      ))}
      {s.publishes.length > 0 && (
        <p className="svc-publica suave">Publica: {s.publishes.join(", ")}</p>
      )}
      {!caido && (
        <dl className="svc-detalles">
          {detallesDe(s).map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}
      {s.problems.length > 0 && (
        <ul className="svc-problemas">
          {s.problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
    </article>
  );
}

export default function Admin() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);
  const [actualizando, setActualizando] = useState(false);
  const [ahora, setAhora] = useState(Date.now());

  const cargar = useCallback(async () => {
    setActualizando(true);
    try {
      setDatos(await get("/admin/status"));
      setError(null);
    } catch (e) {
      setError([502, 503, 504].includes(e.status)
        ? "El gateway no responde."
        : e.status === 403 ? "Solo un administrador puede ver este panel." : `No se pudo cargar el estado (${e.message}).`);
    } finally {
      setActualizando(false);
    }
  }, []);

  useEffect(() => {
    cargar();
    const t = setInterval(cargar, REFRESCO_MS);
    const reloj = setInterval(() => setAhora(Date.now()), 1000);
    return () => {
      clearInterval(t);
      clearInterval(reloj);
    };
  }, [cargar]);

  const hace = datos ? Math.max(0, Math.round((ahora - Date.parse(datos.checked_at)) / 1000)) : null;
  const infra = datos?.infrastructure;

  return (
    <section className="admin">
      <div className="feed-cabecera">
        <h1>Panel del sistema</h1>
        <span className="admin-acciones">
          {datos && <Etiqueta estado={datos.status} />}
          <span className="suave">{hace != null ? `Actualizado hace ${hace} s` : ""}</span>
          <button type="button" className="boton boton-secundario" onClick={cargar} disabled={actualizando}>
            {actualizando ? "Actualizando…" : "↻ Actualizar"}
          </button>
        </span>
      </div>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {!datos && !error && <p className="suave">Consultando los servicios…</p>}
      {datos && (
        <>
          <div className="svc-grid">
            {datos.services.map((s) => <Tarjeta key={s.service} s={s} />)}
          </div>
          <h2 className="admin-subtitulo">Infraestructura</h2>
          <div className="svc-grid svc-grid-infra">
            <article className={`tarjeta svc svc-${infra.gateway.status}`}>
              <header className="svc-cabecera"><h2 className="tarjeta-titulo">API Gateway</h2><Etiqueta estado={infra.gateway.status} /></header>
              <p className="suave svc-publica">Valida el token y enruta REST y WebSocket.</p>
            </article>
            <article className={`tarjeta svc svc-${infra.rabbitmq.status}`}>
              <header className="svc-cabecera"><h2 className="tarjeta-titulo">RabbitMQ</h2><Etiqueta estado={infra.rabbitmq.status} /></header>
              <p className="suave svc-publica">
                {infra.rabbitmq.status === "ok"
                  ? `v${infra.rabbitmq.version} · ${infra.rabbitmq.queues} colas (${infra.rabbitmq.quorum_queues} quorum)`
                  : "No se pudo consultar el broker."}
              </p>
            </article>
            <article className={`tarjeta svc svc-${infra.frontend.status}`}>
              <header className="svc-cabecera"><h2 className="tarjeta-titulo">Frontend</h2><Etiqueta estado={infra.frontend.status} /></header>
              <p className="suave svc-publica">React servido por Nginx.</p>
            </article>
          </div>
        </>
      )}
    </section>
  );
}
