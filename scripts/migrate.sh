#!/usr/bin/env bash
set -euo pipefail

docker compose run --rm backend alembic -c backend/alembic.ini upgrade head

