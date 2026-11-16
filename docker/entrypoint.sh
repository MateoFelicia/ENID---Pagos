#!/bin/sh
# Aplica las migraciones de la base y recién después arranca lo que se pida.
set -e
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    flask db upgrade
fi
exec "$@"
