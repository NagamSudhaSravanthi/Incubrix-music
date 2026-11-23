"""python scripts/export_openapi.py  -> writes openapi.yaml (OpenAPI 3.1) from the running app code."""
import sys
import yaml
sys.path.insert(0, ".")
from app.api.main import app

with open("openapi.yaml", "w") as f:
    yaml.safe_dump(app.openapi(), f, sort_keys=False, allow_unicode=True)
print("wrote openapi.yaml, openapi version", app.openapi()["openapi"])
