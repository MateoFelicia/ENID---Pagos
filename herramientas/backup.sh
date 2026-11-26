#!/usr/bin/env bash
# Copia de seguridad de la base de datos (comprimida) y limpieza de copias viejas.
# Uso:  herramientas/backup.sh [carpeta_destino] [dias_a_conservar]
#   - Con docker compose (base "db"): usa pg_dump dentro del contenedor.
#   - Con DATABASE_URL de PostgreSQL: usa pg_dump (tiene que estar instalado).
#   - Con SQLite: copia consistente del archivo.
# Programalo a diario:  0 4 * * *  cd /ruta/a/enid && herramientas/backup.sh /ruta/backups 14
set -euo pipefail

DESTINO="${1:-./backups}"
DIAS="${2:-14}"
mkdir -p "$DESTINO"
SELLO="$(date +%Y%m%d-%H%M%S)"

if [ -f docker-compose.yml ] && command -v docker >/dev/null 2>&1 && [ -n "$(docker compose ps -q db 2>/dev/null)" ]; then
    ARCHIVO="$DESTINO/enid-$SELLO.sql.gz"
    docker compose exec -T db pg_dump -U enid --no-owner enid | gzip > "$ARCHIVO"
elif [[ "${DATABASE_URL:-}" == postgres* ]]; then
    ARCHIVO="$DESTINO/enid-$SELLO.sql.gz"
    pg_dump --no-owner "${DATABASE_URL/postgres:\/\//postgresql://}" | gzip > "$ARCHIVO"
else
    RUTA="${SQLITE_PATH:-instance/pagos.db}"
    [ -f "$RUTA" ] || { echo "No encuentro la base SQLite en $RUTA (definí SQLITE_PATH)" >&2; exit 1; }
    ARCHIVO="$DESTINO/enid-$SELLO.db"
    python3 - "$RUTA" "$ARCHIVO" <<'PY'
import sqlite3, sys
origen = sqlite3.connect(sys.argv[1])
destino = sqlite3.connect(sys.argv[2])
origen.backup(destino)
destino.close(); origen.close()
PY
    gzip "$ARCHIVO"; ARCHIVO="$ARCHIVO.gz"
fi

# Una copia vacía no sirve: avisar en lugar de aparentar que todo salió bien
[ -s "$ARCHIVO" ] || { echo "La copia quedó vacía: $ARCHIVO" >&2; rm -f "$ARCHIVO"; exit 1; }
find "$DESTINO" -name 'enid-*' -mtime +"$DIAS" -delete
echo "Copia lista: $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"
