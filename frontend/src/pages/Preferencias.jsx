// Registro, entrada por email y preferencias. Responsable: Ariana.
// Usa (Usuarios, docs/arquitectura.md sección 7):
//   POST /api/users                    registro
//   GET  /api/users?email=             volver a entrar sin contraseña
//   GET  /api/users/{id}               datos y preferencias del usuario actual
//   PUT  /api/users/{id}/preferences   reemplaza categorías, keywords y notificaciones
//                                      (Usuarios publica user.preferences.updated)
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get, post, put } from "../api.js";
import { clearUser, getUserId, setUserId } from "../user.js";

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

function textoError(error, contexto) {
  if ([502, 503, 504].includes(error.status)) {
    return "El servicio de usuarios no está disponible. Intenta de nuevo en un momento.";
  }
  if (error.status === 409) return "Ese email ya está registrado. Entra con él en «Ya tengo cuenta».";
  if (error.status === 404 && contexto === "entrar") return "No hay ninguna cuenta con ese email.";
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

// ---------------------------------------------------------------------------
// Sin usuario: registro o entrada por email
// ---------------------------------------------------------------------------
function Acceso({ onEntrar }) {
  const [modo, setModo] = useState("registro");
  const [email, setEmail] = useState("");
  const [nombre, setNombre] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState(null);

  async function enviar(evento) {
    evento.preventDefault();
    setEnviando(true);
    setAviso(null);
    try {
      const usuario =
        modo === "registro"
          ? await post("/users", { email: email.trim(), name: nombre.trim() })
          : await get(`/users?email=${encodeURIComponent(email.trim())}`);
      onEntrar(usuario, modo === "registro" ? "Cuenta creada. Ahora elige tus intereses." : `Hola de nuevo, ${usuario.name}.`);
    } catch (error) {
      setAviso({ tipo: "error", texto: textoError(error, modo === "registro" ? "registro" : "entrar") });
      if (error.status === 409) setModo("entrar");
    } finally {
      setEnviando(false);
    }
  }

  function cambiarModo(nuevo) {
    setModo(nuevo);
    setAviso(null);
  }

  return (
    <section className="tarjeta">
      <div className="pestanas" role="tablist">
        <button type="button" role="tab" aria-selected={modo === "registro"}
                className={modo === "registro" ? "pestana activa" : "pestana"} onClick={() => cambiarModo("registro")}>
          Crear cuenta
        </button>
        <button type="button" role="tab" aria-selected={modo === "entrar"}
                className={modo === "entrar" ? "pestana activa" : "pestana"} onClick={() => cambiarModo("entrar")}>
          Ya tengo cuenta
        </button>
      </div>

      <form onSubmit={enviar} className="formulario">
        <label className="campo">
          <span>Email</span>
          <input type="email" required autoComplete="email" value={email}
                 onChange={(e) => setEmail(e.target.value)} placeholder="nombre@ejemplo.com" />
        </label>
        {modo === "registro" && (
          <label className="campo">
            <span>Nombre</span>
            <input type="text" required maxLength={100} autoComplete="name" value={nombre}
                   onChange={(e) => setNombre(e.target.value)} />
          </label>
        )}
        <Aviso aviso={aviso} />
        <button type="submit" className="boton" disabled={enviando}>
          {enviando ? "Enviando…" : modo === "registro" ? "Crear cuenta" : "Entrar"}
        </button>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Con usuario: edición de preferencias
// ---------------------------------------------------------------------------
function EditorPreferencias({ usuario, avisoInicial, onActualizado, onSalir }) {
  const prefs = usuario.preferences ?? {};
  const [categorias, setCategorias] = useState(prefs.categories ?? []);
  const [keywords, setKeywords] = useState((prefs.keywords ?? []).join(", "));
  const [activadas, setActivadas] = useState(prefs.notifications_enabled ?? true);
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState(avisoInicial);

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
      });
      onActualizado(actualizado);
      setKeywords(actualizado.preferences.keywords.join(", "));
      setAviso({ tipo: "ok", texto: "Preferencias guardadas. Las nuevas alertas ya las tendrán en cuenta." });
    } catch (error) {
      setAviso({ tipo: "error", texto: textoError(error, "guardar") });
    } finally {
      setGuardando(false);
    }
  }

  const sinIntereses = categorias.length === 0 && listaKeywords.length === 0;

  return (
    <>
      <section className="tarjeta usuario-actual">
        <div>
          <strong>{usuario.name}</strong>
          <span className="suave">{usuario.email}</span>
        </div>
        <button type="button" className="boton boton-secundario" onClick={onSalir}>
          Cambiar de usuario
        </button>
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

// ---------------------------------------------------------------------------
export default function Preferencias() {
  const [usuario, setUsuario] = useState(null);
  const [cargando, setCargando] = useState(Boolean(getUserId()));
  const [aviso, setAviso] = useState(null);

  // Usuario guardado en el navegador: recargar sus datos
  useEffect(() => {
    const id = getUserId();
    if (!id) return;
    let vigente = true;
    get(`/users/${encodeURIComponent(id)}`)
      .then((u) => vigente && setUsuario(u))
      .catch((error) => {
        if (!vigente) return;
        if (error.status === 404 || error.status === 422) {
          clearUser(); // el usuario ya no existe: volver al registro
        } else {
          setAviso({ tipo: "error", texto: textoError(error, "cargar") });
        }
      })
      .finally(() => vigente && setCargando(false));
    return () => {
      vigente = false;
    };
  }, []);

  function entrar(u, mensaje) {
    setUserId(u.user_id);
    setUsuario(u);
    setAviso({ tipo: "ok", texto: mensaje });
  }

  function salir() {
    clearUser();
    setUsuario(null);
    setAviso(null);
  }

  return (
    <section className="preferencias">
      <h1>Preferencias</h1>
      {cargando ? (
        <p className="suave">Cargando tu cuenta…</p>
      ) : usuario ? (
        <EditorPreferencias key={usuario.user_id} usuario={usuario} avisoInicial={aviso}
                            onActualizado={setUsuario} onSalir={salir} />
      ) : (
        <>
          <p className="suave">Crea una cuenta o entra con tu email para elegir qué noticias quieres recibir.</p>
          {aviso && <Aviso aviso={aviso} />}
          <Acceso onEntrar={entrar} />
        </>
      )}
    </section>
  );
}
