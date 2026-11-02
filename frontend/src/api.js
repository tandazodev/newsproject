// Cliente REST: el navegador solo habla con /api (Nginx o el proxy de Vite).
// Envía el JWT de la sesión; si el gateway responde 401 con una sesión abierta,
// la sesión venció: se cierra y se vuelve a la pantalla de inicio de sesión.
import { clearUser, getToken } from "./user.js";

async function request(method, ruta, body) {
  const opciones = { method, headers: { Accept: "application/json" } };
  const token = getToken();
  if (token) opciones.headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(body);
  }

  const res = await fetch("/api" + ruta, opciones);
  const texto = await res.text();
  let datos = null;
  try {
    datos = texto ? JSON.parse(texto) : null;
  } catch {
    datos = null;
  }

  if (res.status === 401 && token) {
    clearUser();
    window.location.assign(`/login?vencida=1`);
  }

  if (!res.ok) {
    const detalle = datos?.detail ?? datos?.error ?? datos?.message;
    const mensaje =
      (typeof detalle === "string" ? detalle : detalle && JSON.stringify(detalle)) ||
      texto ||
      res.statusText;
    const error = new Error(`${res.status}: ${mensaje}`);
    error.status = res.status;
    error.data = datos;
    throw error;
  }
  return datos;
}

export const get = (ruta) => request("GET", ruta);
export const post = (ruta, body) => request("POST", ruta, body);
export const put = (ruta, body) => request("PUT", ruta, body);
export const patch = (ruta, body) => request("PATCH", ruta, body);
