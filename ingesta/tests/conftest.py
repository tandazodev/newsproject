import sys
from pathlib import Path

# app.config tiene valores por defecto; las pruebas no se conectan a nada.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
