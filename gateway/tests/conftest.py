import os
import sys
from pathlib import Path

# app.main lee estas variables al importarse; las pruebas no se conectan a nada.
for nombre, url in {"INGESTA_URL": "http://ingesta:8000", "CLASIFICACION_URL": "http://clasificacion:8000",
                    "BUSQUEDA_URL": "http://busqueda:8000", "USUARIOS_URL": "http://usuarios:8000",
                    "NOTIFICACIONES_URL": "http://notificaciones:8080"}.items():
    os.environ.setdefault(nombre, url)
os.environ.setdefault("JWT_SECRET", "secreto-de-prueba-de-al-menos-32-caracteres")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
