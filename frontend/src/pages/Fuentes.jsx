// Fuentes de noticias. Responsable: Kevin.
// Usa (docs/arquitectura.md secciones 7 y 7.1):
//   GET  /api/sources                    lista de fuentes con su último estado (todos)
//   POST /api/sources                    registra una fuente nueva (solo administrador)
//   POST /api/sources/{id}/scrape        scraping manual; 202 Accepted (solo administrador)
//   GET  /api/users/me, PUT /api/users/{id}/preferences   fuentes apagadas en mi feed
//                                        (disabled_sources, docs/eventos.md 3.5)
// El scraping corre en segundo plano en Ingesta: tras el 202 se muestra "En proceso"
// y se consulta la lista hasta que aparece una ejecución nueva de esa fuente.
import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, put } from "../api.js";
import { isAdmin, setUser } from "../user.js";

const INTERVALO_MS = 2000; // cada cuánto se refresca mientras hay scrapings en curso
const ESPERA_MAX_MS = 90000; // después de esto se deja de esperar y se avisa

const formatoFecha = new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" });

function fecha(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : formatoFecha.format(d);
}

function textoError(error) {
  if ([502, 503, 504].includes(error.status)) {
    return "El servicio de ingesta no está disponible. Intenta de nuevo en un momento.";
  }
  if (error.status === 409) return "Esa URL ya está registrada como fuente.";
  if (error.status === 422) {
    const detalle = error.data?.detail;
    if (Array.isArray(detalle) && detalle.some((d) => d.loc?.includes("url"))) {
      return "La URL no es válida. Debe empezar por http:// o https://.";
    }
    return "Revisa los datos del formulario.";
  }
  return `No se pudo completar la operación (${error.message}).`;
}

function Aviso({ aviso }) {
  if (!aviso) return null;
  return (
    <p className={`aviso aviso-${aviso.tipo}`} role={aviso.tipo === "error" ? "alert" : "status"}>
      {aviso.texto}
    </p>
  );
}

function Estado({ fuente, enProceso }) {
  if (enProceso) return <span className="estado estado-proceso">En proceso…</span>;
  if (!fuente.active) return <span className="estado estado-inactiva">Inactiva</span>;
  const ultimo = fuente.last_scrape;
  if (!ultimo) return <span className="estado estado-nunca">Sin ejecutar</span>;
  return ultimo.status === "ok"
    ? <span className="estado estado-ok">OK</span>
    : <span className="estado estado-error">Con errores</span>;
}

function Resumen({ ultimo }) {
  if (!ultimo) return <p className="suave fuente-resumen">Aún no se ha scrapeado esta fuente.</p>;
  return (
    <p className="suave fuente-resumen">
      Última ejecución: {fecha(ultimo.finished_at ?? ultimo.started_at)} · {ultimo.found} encontradas ·{" "}
      <strong>{ultimo.new} nuevas</strong> · {ultimo.updated} actualizadas
      {ultimo.errors > 0 && <> · <span className="texto-error">{ultimo.errors} errores</span></>}
    </p>
  );
}

// ---------------------------------------------------------------------------
function FormularioFuente({ onCreada }) {
  const [nombre, setNombre] = useState("");
  const [url, setUrl] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState(null);

  async function enviar(evento) {
    evento.preventDefault();
    setEnviando(true);
    setAviso(null);
    try {
      const fuente = await post("/sources", { name: nombre.trim(), url: url.trim(), active: true });
      setNombre("");
      setUrl("");
      setAviso({ tipo: "ok", texto: `Fuente «${fuente.name}» agregada. Pulsa «Scrapear» para traer sus noticias.` });
      onCreada();
    } catch (error) {
      setAviso({ tipo: "error", texto: textoError(error) });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} className="tarjeta formulario">
      <h2 className="tarjeta-titulo">Agregar fuente</h2>
      <div className="fila-campos">
        <label className="campo">
          <span>Nombre</span>
          <input type="text" required maxLength={100} value={nombre}
                 onChange={(e) => setNombre(e.target.value)} placeholder="BBC Mundo" />
        </label>
        <label className="campo campo-ancho">
          <span>URL del feed RSS</span>
          <input type="url" required value={url}
                 onChange={(e) => setUrl(e.target.value)} placeholder="https://feeds.bbci.co.uk/mundo/rss.xml" />
        </label>
      </div>
      <button type="submit" className="boton" disabled={enviando}>
        {enviando ? "Agregando…" : "Agregar fuente"}
      </button>
      <Aviso aviso={aviso} />
    </form>
  );
}

// ---------------------------------------------------------------------------
export default function Fuentes() {
  const [fuentes, setFuentes] = useState(null);
  const [error, setError] = useState(null);
  // id -> { desde: started_at de la última ejecución antes del 202, inicio: ms }
  const [enProceso, setEnProceso] = useState({});
  const [avisos, setAvisos] = useState({}); // id -> aviso del último scraping
  const enProcesoRef = useRef(enProceso);
  enProcesoRef.current = enProceso;
  const admin = isAdmin();
  const [usuario, setUsuario] = useState(null); // para las fuentes apagadas en mi feed
  const [cambiando, setCambiando] = useState(null); // id de la fuente que se está guardando

  useEffect(() => {
    get("/users/me").then(setUsuario).catch(() => setUsuario(null));
  }, []);

  const apagadas = new Set(usuario?.preferences?.disabled_sources ?? []);

  async function alternarEnFeed(fuente) {
    if (!usuario) return;
    const p = usuario.preferences;
    const nuevas = apagadas.has(fuente.id)
      ? [...apagadas].filter((id) => id !== fuente.id)
      : [...apagadas, fuente.id];
    const anterior = usuario;
    // Optimista: el interruptor cambia al instante y se revierte si el guardado falla
    setUsuario({ ...usuario, preferences: { ...p, disabled_sources: nuevas } });
    setCambiando(fuente.id);
    setAvisos((a) => ({ ...a, [fuente.id]: null }));
    try {
      // PUT reemplaza todas las preferencias: se reenvían las actuales con la lista nueva
      const actualizado = await put(`/users/${usuario.user_id}/preferences`, {
        categories: p.categories,
        keywords: p.keywords,
        notifications_enabled: p.notifications_enabled,
        disabled_sources: nuevas,
      });
      setUsuario(actualizado);
      setUser(actualizado);
    } catch (e) {
      setUsuario(anterior);
      setAvisos((a) => ({ ...a, [fuente.id]: { tipo: "error", texto: textoError(e) } }));
    } finally {
      setCambiando(null);
    }
  }

  const cargar = useCallback(async () => {
    try {
      const lista = await get("/sources");
      setFuentes(lista);
      setError(null);
      return lista;
    } catch (e) {
      setError(textoError(e));
      return null;
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  // Mientras haya scrapings en curso, refrescar hasta ver una ejecución nueva de cada fuente
  const hayEnProceso = Object.keys(enProceso).length > 0;
  useEffect(() => {
    if (!hayEnProceso) return undefined;
    const temporizador = setInterval(async () => {
      const lista = await cargar();
      if (!lista) return;
      const pendientes = { ...enProcesoRef.current };
      const nuevosAvisos = {};
      for (const [id, { desde, inicio }] of Object.entries(pendientes)) {
        const ultimo = lista.find((f) => f.id === id)?.last_scrape;
        const terminado = ultimo?.finished_at && ultimo.started_at !== desde;
        if (terminado) {
          delete pendientes[id];
          nuevosAvisos[id] = ultimo.status === "ok"
            ? { tipo: "ok", texto: `Listo: ${ultimo.new} noticias nuevas y ${ultimo.updated} actualizadas.` }
            : { tipo: "error", texto: "El scraping terminó con errores (revisa que la URL del feed responda)." };
        } else if (Date.now() - inicio > ESPERA_MAX_MS) {
          delete pendientes[id];
          nuevosAvisos[id] = { tipo: "info", texto: "Sigue en proceso. Actualiza la página en un momento para ver el resultado." };
        }
      }
      if (Object.keys(nuevosAvisos).length > 0) {
        setEnProceso(pendientes);
        setAvisos((a) => ({ ...a, ...nuevosAvisos }));
      }
    }, INTERVALO_MS);
    return () => clearInterval(temporizador);
  }, [hayEnProceso, cargar]);

  async function scrapear(fuente) {
    setAvisos((a) => ({ ...a, [fuente.id]: null }));
    try {
      await post(`/sources/${fuente.id}/scrape`); // 202 Accepted
      setEnProceso((p) => ({
        ...p,
        [fuente.id]: { desde: fuente.last_scrape?.started_at ?? null, inicio: Date.now() },
      }));
    } catch (e) {
      setAvisos((a) => ({ ...a, [fuente.id]: { tipo: "error", texto: textoError(e) } }));
    }
  }

  return (
    <section className="fuentes">
      <h1>Fuentes</h1>
      <p className="suave">
        Las fuentes se revisan solas cada pocos minutos. Apaga las que no quieras ver en tu feed
        {admin ? "; como administrador también puedes agregar fuentes y scrapearlas ahora." : "."}
      </p>

      {admin && <FormularioFuente onCreada={cargar} />}

      {error && (
        <div className="aviso aviso-error fuentes-error" role="alert">
          <span>{error}</span>
          <button type="button" className="boton boton-secundario" onClick={cargar}>Reintentar</button>
        </div>
      )}
      {fuentes === null && !error && <p className="suave">Cargando fuentes…</p>}
      {fuentes?.length === 0 && <p className="suave">No hay fuentes registradas.</p>}

      {fuentes?.length > 0 && (
        <ul className="lista-fuentes">
          {fuentes.map((f) => {
            const ocupada = Boolean(enProceso[f.id]);
            return (
              <li key={f.id} className="tarjeta fuente">
                <div className="fuente-cabecera">
                  <div className="fuente-datos">
                    <h2 className="tarjeta-titulo">{f.name}</h2>
                    <a href={f.url} target="_blank" rel="noopener noreferrer" className="fuente-url">{f.url}</a>
                  </div>
                  <Estado fuente={f} enProceso={ocupada} />
                  <label className="interruptor-feed" title="Mostrar las noticias de esta fuente en mi feed">
                    <input type="checkbox" role="switch" checked={!apagadas.has(f.id)}
                           disabled={!usuario} onChange={() => cambiando !== f.id && alternarEnFeed(f)} />
                    En mi feed
                  </label>
                  {admin && (
                    <button type="button" className="boton" onClick={() => scrapear(f)}
                            disabled={ocupada || !f.active}
                            title={f.active ? undefined : "La fuente está inactiva"}>
                      {ocupada ? "En proceso…" : "Scrapear"}
                    </button>
                  )}
                </div>
                <Resumen ultimo={f.last_scrape} />
                <Aviso aviso={avisos[f.id]} />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
