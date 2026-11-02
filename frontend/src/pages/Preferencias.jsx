// Preferencias del usuario con sesión. Responsable: Ariana.
// Usa (Usuarios, docs/arquitectura.md secciones 7 y 7.1):
//   GET /api/users/me                    datos y preferencias del usuario del token
//   PUT /api/users/{id}/preferences      reemplaza categorías, keywords, notificaciones y
//                                        fuentes desactivadas (publica user.preferences.updated)
// El registro y el inicio de sesión están en Registro.jsx y Login.jsx. Tras registrarse se
// llega aquí con ?nuevo=1: al guardar las primeras preferencias se va al feed.
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { get, put } from "../api.js";
import { setUser } from "../user.js";

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
const MAX_KEYWORDS = 20;
const MAX_LARGO_KEYWORD = 50;

function textoError(error) {
  if ([502, 503, 504].includes(error.status)) {
    return "El servicio de usuarios no está disponible. Intenta de nuevo en un momento.";
  }
  if (error.status === 422) return `Datos no válidos: ${error.message.replace(/^422: /, "")}`;
  return `No se pudo completar la operación (${error.message}).`;
}

// "IA, Ecuador,  rabbitmq" -> ["ia", "ecuador", "rabbitmq"] (sin vacíos ni repetidos)
function separarKeywords(texto) {
  const vistas = new Set();
  return texto
    .split(",")
    .map((k) => k.trim().toLowerCase())
    .filter((k) => k && !vistas.has(k) && vistas.add(k));
}

function Aviso({ aviso }) {
  if (!aviso) return null;
  return (
    <p className={`aviso aviso-${aviso.tipo}`} role={aviso.tipo === "error" ? "alert" : "status"}>
      {aviso.texto}
    </p>
  );
}

function EditorPreferencias({ usuario, esNuevo, onActualizado }) {
  const navigate = useNavigate();
  const prefs = usuario.preferences ?? {};
  const [categorias, setCategorias] = useState(prefs.categories ?? []);
  const [keywords, setKeywords] = useState((prefs.keywords ?? []).join(", "));
  const [activadas, setActivadas] = useState(prefs.notifications_enabled ?? true);
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState(
    esNuevo ? { tipo: "ok", texto: `Cuenta creada. Bienvenido, ${usuario.first_names}: elige tus intereses.` } : null
  );

  const listaKeywords = separarKeywords(keywords);
  const keywordLarga = listaKeywords.find((k) => k.length > MAX_LARGO_KEYWORD);
  const errorLocal = keywordLarga
    ? `La palabra clave «${keywordLarga.slice(0, 20)}…» supera los ${MAX_LARGO_KEYWORD} caracteres.`
    : listaKeywords.length > MAX_KEYWORDS
      ? `Máximo ${MAX_KEYWORDS} palabras clave (hay ${listaKeywords.length}).`
      : null;

  function alternar(categoria) {
    setCategorias((actuales) =>
      actuales.includes(categoria) ? actuales.filter((c) => c !== categoria) : [...actuales, categoria]
    );
    setAviso(null);
  }

  async function guardar(evento) {
    evento.preventDefault();
    if (errorLocal) return;
    setGuardando(true);
    setAviso(null);
    try {
      // Orden oficial, para que la lista guardada no dependa del orden de los clics
      const ordenadas = Object.keys(CATEGORIAS).filter((c) => categorias.includes(c));
      const actualizado = await put(`/users/${usuario.user_id}/preferences`, {
        categories: ordenadas,
        keywords: listaKeywords,
        notifications_enabled: activadas,
        // PUT reemplaza todo: se conservan las fuentes que el usuario apagó en Fuentes
        disabled_sources: usuario.preferences?.disabled_sources ?? [],
      });
      onActualizado(actualizado);
      const conIntereses = actualizado.preferences.categories.length > 0 || actualizado.preferences.keywords.length > 0;
      if (esNuevo && conIntereses) {
        navigate("/feed");
        return;
      }
      setKeywords(actualizado.preferences.keywords.join(", "));
      setAviso({ tipo: "ok", texto: "Preferencias guardadas. Las nuevas alertas ya las tendrán en cuenta." });
    } catch (error) {
      setAviso({ tipo: "error", texto: textoError(error) });
    } finally {
      setGuardando(false);
    }
  }

  const sinIntereses = categorias.length === 0 && listaKeywords.length === 0;
  const apagadas = usuario.preferences?.disabled_sources?.length ?? 0;

  return (
    <>
      <section className="tarjeta usuario-actual">
        <div>
          <strong>{usuario.first_names} {usuario.last_names}</strong>
          <span className="suave">@{usuario.username} · {usuario.email}{usuario.role === "admin" ? " · administrador" : ""}</span>
        </div>
      </section>

      <form onSubmit={guardar} className="tarjeta formulario">
        <fieldset className="casillas">
          <legend>Categorías que te interesan</legend>
          {Object.entries(CATEGORIAS).map(([valor, etiqueta]) => (
            <label key={valor} className="casilla">
              <input type="checkbox" checked={categorias.includes(valor)} onChange={() => alternar(valor)} />
              {etiqueta}
            </label>
          ))}
        </fieldset>

        <label className="campo">
          <span>Palabras clave</span>
          <input type="text" value={keywords} onChange={(e) => { setKeywords(e.target.value); setAviso(null); }}
                 placeholder="ecuador, inteligencia artificial, rabbitmq" aria-describedby="ayuda-keywords" />
          <small id="ayuda-keywords" className="suave">
            Separadas por comas. Te avisamos si aparecen en el título o en las etiquetas de una noticia.
          </small>
        </label>

        <label className="casilla interruptor">
          <input type="checkbox" checked={activadas} onChange={(e) => { setActivadas(e.target.checked); setAviso(null); }} />
          Recibir notificaciones en el feed
        </label>

        <p className="suave pie">
          {apagadas > 0 ? `Tienes ${apagadas} fuente(s) apagada(s) en tu feed. ` : ""}
          Elige qué fuentes ver en tu feed desde <Link to="/fuentes">Fuentes</Link>.
        </p>

        <div className="acciones">
          <button type="submit" className="boton" disabled={guardando || Boolean(errorLocal)}>
            {guardando ? "Guardando…" : "Guardar preferencias"}
          </button>
          <Link to="/feed" className="enlace">Ir al feed →</Link>
        </div>

        {/* Avisos debajo del botón: al aparecer o desaparecer no lo desplazan */}
        {errorLocal && <p className="aviso aviso-error" role="alert">{errorLocal}</p>}
        {!errorLocal && activadas && sinIntereses && (
          <p className="aviso aviso-info">Sin categorías ni palabras clave no recibirás ninguna alerta.</p>
        )}
        <Aviso aviso={aviso} />
        {usuario.preferences?.updated_at && (
          <p className="suave pie">
            Última actualización: {new Date(usuario.preferences.updated_at).toLocaleString("es-EC")}
          </p>
        )}
      </form>
    </>
  );
}

export default function Preferencias() {
  const [params] = useSearchParams();
  const [usuario, setUsuario] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let vigente = true;
    get("/users/me")
      .then((u) => {
        if (!vigente) return;
        setUsuario(u);
        setUser(u);
      })
      .catch((e) => vigente && setError(textoError(e)));
    return () => {
      vigente = false;
    };
  }, []);

  function actualizado(u) {
    setUsuario(u);
    setUser(u);
  }

  return (
    <section className="preferencias">
      <h1>Preferencias</h1>
      {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      {!usuario && !error && <p className="suave">Cargando tu cuenta…</p>}
      {usuario && (
        <EditorPreferencias key={usuario.user_id} usuario={usuario} esNuevo={params.get("nuevo") === "1"}
                            onActualizado={actualizado} />
      )}
    </section>
  );
}
