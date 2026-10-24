#!/bin/sh
set -eu
: "${SEARXNG_SECRET:?Set SEARXNG_SECRET in docker/.env before starting the search service}"
exec "$@"
