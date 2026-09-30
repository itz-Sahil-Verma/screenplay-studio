#!/usr/bin/env bash
# Regenerate the frontend's TypeScript types from the FastAPI OpenAPI schema.
# Run after changing any response/request model in app/api/routes.py.
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -c "import json; from app.main import app; json.dump(app.openapi(), open('app/web/openapi.json','w'), indent=1)"
(cd app/web && npx openapi-typescript openapi.json -o src/lib/api-types.ts)
echo "types regenerated"
