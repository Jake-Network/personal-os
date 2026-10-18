#!/bin/sh
set -eu

python -m app.modules.database.startup_migration
exec "$@"
