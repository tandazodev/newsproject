// Barra superior común a todas las páginas.
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useNotificaciones } from "../context/NotificacionesContext.jsx";
import { clearUser, getUser } from "../user.js";

const enlace = ({ isActive }) => (isActive ? "nav-link active" : "nav-link");

export default function Layout() {
  const { unread, setUnread } = useNotificaciones();
  const navigate = useNavigate();
  useLocation(); // vuelve a pintar la barra al navegar (p. ej. tras iniciar sesión)
  const usuario = getUser();

  function salir() {
    clearUser();
    setUnread(0);
    navigate("/login", { replace: true });
  }

  return (
    <>
      <header className="barra">
        <span className="marca">Agregador de Noticias</span>
        {usuario ? (
          <nav className="menu">
            <NavLink to="/feed" className={enlace}>
              Feed
              {unread > 0 && <span className="badge">{unread}</span>}
            </NavLink>
            <NavLink to="/buscar" className={enlace}>Buscar</NavLink>
            <NavLink to="/fuentes" className={enlace}>Fuentes</NavLink>
            <NavLink to="/preferencias" className={enlace}>Preferencias</NavLink>
            {usuario.role === "admin" && <NavLink to="/admin" className={enlace}>Panel</NavLink>}
            <span className="sesion">
              <span className="sesion-nombre" title={usuario.email}>{usuario.username}</span>
              {usuario.role === "admin" && <span className="rol">admin</span>}
              <button type="button" className="nav-link boton-salir" onClick={salir}>Cerrar sesión</button>
            </span>
          </nav>
        ) : (
          <nav className="menu">
            <NavLink to="/login" className={enlace}>Iniciar sesión</NavLink>
            <NavLink to="/registro" className={enlace}>Crear cuenta</NavLink>
          </nav>
        )}
      </header>
      <main className="contenido">
        <Outlet />
      </main>
    </>
  );
}
