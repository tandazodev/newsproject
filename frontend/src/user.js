// Sesión actual (token JWT + datos del usuario) en localStorage. Puede fallar
// (modo privado, almacenamiento bloqueado): en ese caso no hay sesión.
const CLAVE = "newsproject.session";

function leer() {
  try {
    const sesion = JSON.parse(localStorage.getItem(CLAVE) ?? "null");
    if (!sesion?.token || !sesion?.user) return null;
    if (tokenVencido(sesion.token)) {
      localStorage.removeItem(CLAVE);
      return null;
    }
    return sesion;
  } catch {
    return null;
  }
}

// exp del JWT (sin verificar la firma: eso lo hace el gateway)
function tokenVencido(token) {
  try {
    const base64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const { exp } = JSON.parse(atob(base64));
    return typeof exp === "number" && exp * 1000 <= Date.now();
  } catch {
    return true;
  }
}

export function getSession() {
  return leer();
}

export function getToken() {
  return leer()?.token ?? null;
}

export function getUser() {
  return leer()?.user ?? null;
}

export function getUserId() {
  return leer()?.user?.user_id ?? null;
}

export function isAdmin() {
  return leer()?.user?.role === "admin";
}

export function setSession(token, user) {
  try {
    localStorage.setItem(CLAVE, JSON.stringify({ token, user }));
  } catch {
    // sin almacenamiento: habrá que iniciar sesión de nuevo al recargar
  }
}

// Actualiza los datos del usuario (p. ej. tras guardar preferencias) sin tocar el token
export function setUser(user) {
  const sesion = leer();
  if (sesion) setSession(sesion.token, user);
}

export function clearUser() {
  try {
    localStorage.removeItem(CLAVE);
    localStorage.removeItem("newsproject.userId"); // clave de la versión anterior, sin contraseña
  } catch {
    // nada que borrar
  }
}
