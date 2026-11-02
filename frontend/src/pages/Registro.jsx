// Registro público (POST /api/users): crea siempre un usuario con rol "usuario".
// Tras registrarse inicia sesión y lleva a elegir preferencias (docs/arquitectura.md 7.1).
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { post } from "../api.js";
import { setSession } from "../user.js";

const USERNAME_RE = /^[a-z0-9._-]{3,30}$/;

function textoError(e) {
  if (e.status === 409) return e.message.replace(/^409: /, "").replace(/^./, (c) => c.toUpperCase()) + ".";
  if (e.status === 422) {
    const d = e.data?.detail;
    return typeof d === "string" ? `Revisa los datos: ${d}.` : "Revisa los datos del formulario.";
  }
  if ([502, 503, 504].includes(e.status)) return "El servicio de usuarios no está disponible. Intenta de nuevo en un momento.";
  return `No se pudo completar el registro (${e.message}).`;
}

export default function Registro() {
  const navigate = useNavigate();
  const [datos, setDatos] = useState({
    first_names: "", last_names: "", username: "", email: "", password: "", confirmar: "",
  });
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);

  const cambiar = (campo) => (e) => {
    setDatos((d) => ({ ...d, [campo]: e.target.value }));
    setError(null);
  };

  const username = datos.username.trim().toLowerCase();
  const errorLocal =
    datos.username && !USERNAME_RE.test(username)
      ? "El username debe tener de 3 a 30 caracteres: letras minúsculas, números, «.», «_» o «-»."
      : datos.password && datos.password.length < 8
        ? "La contraseña debe tener al menos 8 caracteres."
        : datos.confirmar && datos.confirmar !== datos.password
          ? "Las contraseñas no coinciden."
          : null;

  async function enviar(evento) {
    evento.preventDefault();
    if (errorLocal) return;
    setEnviando(true);
    setError(null);
    try {
      const email = datos.email.trim();
      await post("/users", {
        email,
        password: datos.password,
        first_names: datos.first_names.trim(),
        last_names: datos.last_names.trim(),
        username,
      });
      const r = await post("/auth/login", { email, password: datos.password });
      setSession(r.access_token, r.user);
      navigate("/preferencias?nuevo=1", { replace: true });
    } catch (e) {
      setError(textoError(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="acceso">
      <h1>Crear cuenta</h1>
      <form onSubmit={enviar} className="tarjeta formulario">
        <div className="fila-campos fila-iguales">
          <label className="campo">
            <span>Nombres</span>
            <input type="text" required maxLength={100} autoComplete="given-name"
                   value={datos.first_names} onChange={cambiar("first_names")} />
          </label>
          <label className="campo">
            <span>Apellidos</span>
            <input type="text" required maxLength={100} autoComplete="family-name"
                   value={datos.last_names} onChange={cambiar("last_names")} />
          </label>
        </div>
        <label className="campo">
          <span>Username</span>
          <input type="text" required maxLength={30} autoComplete="username" value={datos.username}
                 onChange={cambiar("username")} placeholder="ana.perez" aria-describedby="ayuda-username" />
          <small id="ayuda-username" className="suave">3 a 30 caracteres: minúsculas, números, «.», «_» o «-».</small>
        </label>
        <label className="campo">
          <span>Correo</span>
          <input type="email" required autoComplete="email" value={datos.email}
                 onChange={cambiar("email")} placeholder="nombre@ejemplo.com" />
        </label>
        <div className="fila-campos fila-iguales">
          <label className="campo">
            <span>Contraseña</span>
            <input type="password" required minLength={8} maxLength={72} autoComplete="new-password"
                   value={datos.password} onChange={cambiar("password")} />
          </label>
          <label className="campo">
            <span>Repite la contraseña</span>
            <input type="password" required autoComplete="new-password"
                   value={datos.confirmar} onChange={cambiar("confirmar")} />
          </label>
        </div>
        <button type="submit" className="boton" disabled={enviando || Boolean(errorLocal)}>
          {enviando ? "Creando cuenta…" : "Crear cuenta"}
        </button>
        {(errorLocal || error) && <p className="aviso aviso-error" role="alert">{errorLocal || error}</p>}
      </form>
      <p className="suave">¿Ya tienes cuenta? <Link to="/login">Inicia sesión</Link></p>
    </section>
  );
}
