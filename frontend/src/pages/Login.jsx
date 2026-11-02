// Inicio de sesión con correo y contraseña (POST /api/auth/login, docs/arquitectura.md 7.1).
import { useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { post } from "../api.js";
import { setSession } from "../user.js";

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);

  async function enviar(evento) {
    evento.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const r = await post("/auth/login", { email: email.trim(), password });
      setSession(r.access_token, r.user);
      navigate(location.state?.desde ?? "/feed", { replace: true });
    } catch (e) {
      setError(e.status === 401
        ? "Correo o contraseña incorrectos."
        : [502, 503, 504].includes(e.status)
          ? "El servicio de usuarios no está disponible. Intenta de nuevo en un momento."
          : `No se pudo iniciar sesión (${e.message}).`);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="acceso">
      <h1>Iniciar sesión</h1>
      {params.get("vencida") && (
        <p className="aviso aviso-info" role="status">Tu sesión venció. Vuelve a iniciar sesión.</p>
      )}
      <form onSubmit={enviar} className="tarjeta formulario">
        <label className="campo">
          <span>Correo</span>
          <input type="email" required autoComplete="email" value={email}
                 onChange={(e) => setEmail(e.target.value)} placeholder="nombre@ejemplo.com" />
        </label>
        <label className="campo">
          <span>Contraseña</span>
          <input type="password" required autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="boton" disabled={enviando}>
          {enviando ? "Entrando…" : "Entrar"}
        </button>
        {error && <p className="aviso aviso-error" role="alert">{error}</p>}
      </form>
      <p className="suave">¿No tienes cuenta? <Link to="/registro">Regístrate</Link></p>
    </section>
  );
}
