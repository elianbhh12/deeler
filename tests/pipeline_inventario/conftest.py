import sys
from pathlib import Path

# Permite `from python_pipeline import ...` sin instalar el paquete,
# insertando la raiz del repo (BANCO/) en sys.path — python_pipeline vive
# ahi como paquete hermano de core/ y ui/, no dentro de tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
