// Rutas de la app. Sin sesión solo se puede entrar a /login y /registro
// (docs/arquitectura.md, sección 7.1).
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Feed from "./pages/Feed.jsx";
import Buscar from "./pages/Buscar.jsx";
import Fuentes from "./pages/Fuentes.jsx";
import Preferencias from "./pages/Preferencias.jsx";
import Login from "./pages/Login.jsx";
import Registro from "./pages/Registro.jsx";
import Admin from "./pages/Admin.jsx";
import { getSession, isAdmin } from "./user.js";

function RequiereSesion({ children }) {
  const location = useLocation();
  if (!getSession()) return <Navigate to="/login" replace state={{ desde: location.pathname + location.search }} />;
  return children;
}

// Panel del sistema: solo administradores (el gateway además responde 403 al resto)
function SoloAdmin({ children }) {
  return isAdmin() ? children : <Navigate to="/feed" replace />;
}

function SoloSinSesion({ children }) {
  return getSession() ? <Navigate to="/feed" replace /> : children;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/feed" replace />} />
        <Route path="login" element={<SoloSinSesion><Login /></SoloSinSesion>} />
        <Route path="registro" element={<SoloSinSesion><Registro /></SoloSinSesion>} />
        <Route path="feed" element={<RequiereSesion><Feed /></RequiereSesion>} />
        <Route path="buscar" element={<RequiereSesion><Buscar /></RequiereSesion>} />
        <Route path="fuentes" element={<RequiereSesion><Fuentes /></RequiereSesion>} />
        <Route path="preferencias" element={<RequiereSesion><Preferencias /></RequiereSesion>} />
        <Route path="admin" element={<RequiereSesion><SoloAdmin><Admin /></SoloAdmin></RequiereSesion>} />
        <Route path="*" element={<Navigate to="/feed" replace />} />
      </Route>
    </Routes>
  );
}
