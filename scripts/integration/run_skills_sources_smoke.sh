#!/usr/bin/env bash
set -euo pipefail

# 可复刻的 integration 冒烟环境：
# - 启动 redis + postgres
# - 执行 skills catalog pgsql migration（来自已安装的 agent_sdk assets）
# - 运行 `tests/test_integration_sources_redis_pgsql_smoke.py`
#
# 用法：
#   scripts/integration/run_skills_sources_smoke.sh
#   scripts/integration/run_skills_sources_smoke.sh down

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/scripts/integration/docker-compose.skills-sources.yml"
PROJECT_NAME="${ASR_INTEGRATION_PROJECT_NAME:-asr-skills-sources}"

cmd="${1:-up}"

if [[ "$cmd" == "down" ]]; then
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v
  exit 0
fi

docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d

echo "[integration] waiting for redis/pg to be ready..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

for i in {1..60}; do
  if docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" exec -T pg pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" exec -T pg pg_isready -U postgres -d postgres >/dev/null

for i in {1..60}; do
  if docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" exec -T redis redis-cli ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" exec -T redis redis-cli ping >/dev/null

echo "[integration] applying pgsql migration (skills_catalog)..."
MIGRATION_PATH="$(python -c 'import agent_sdk, pathlib; p=(pathlib.Path(agent_sdk.__file__).resolve().parent / "assets/migrations/pgsql/0001_skills_catalog.up.sql"); print(p)' 2>/dev/null || true)"
if [[ -z "$MIGRATION_PATH" || ! -f "$MIGRATION_PATH" ]]; then
  echo "[integration] ERROR: cannot locate agent_sdk pgsql migration file" >&2
  echo "Expected: agent_sdk/assets/migrations/pgsql/0001_skills_catalog.up.sql" >&2
  exit 1
fi

cat "$MIGRATION_PATH" | docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" exec -T pg psql -U postgres -d postgres -v ON_ERROR_STOP=1 >/dev/null

export AGENTLY_SKILLS_RUNTIME_TEST_REDIS_URL="redis://localhost:6379/0"
export AGENTLY_SKILLS_RUNTIME_TEST_PG_DSN="postgresql://postgres:postgres@localhost:5432/postgres"

echo "[integration] running pytest -m integration for redis/pgsql sources smoke..."
cd "$ROOT_DIR"
python -m pytest -m integration -q tests/test_integration_sources_redis_pgsql_smoke.py
