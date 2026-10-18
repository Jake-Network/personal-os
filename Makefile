COMPOSE = docker compose --env-file docker/.env -f docker/docker-compose.yml

.PHONY: db-revision db-upgrade db-current db-history db-check

# Generation uses a one-off container with a writable migrations mount, so the
# revision stays in this checkout. The running app keeps its read-only mount.
db-revision:
	@test -n "$(MESSAGE)" || { echo 'Usage: make db-revision MESSAGE="describe change"'; exit 1; }
	$(COMPOSE) run --rm --no-deps -e PERSONAL_OS_AUTO_MIGRATE=0 -v "$(CURDIR)/migrations:/migration-work:rw" app \
		python -c 'import sys; from alembic import command; from alembic.config import Config; config = Config("alembic.ini"); config.set_main_option("script_location", "/migration-work"); command.revision(config, autogenerate=True, message=sys.argv[1])' "$(MESSAGE)"

db-upgrade:
	$(COMPOSE) exec -T app alembic upgrade head

db-current:
	$(COMPOSE) exec -T app alembic current

db-history:
	$(COMPOSE) exec -T app alembic history --verbose

db-check:
	$(COMPOSE) exec -T app alembic check

.PHONY: db-adopt-legacy db-collation-check
# Works even when app startup refuses an unversioned legacy database.
# Default validates only; APPLY=1 performs the explicit adoption and upgrade.
db-adopt-legacy:
	$(COMPOSE) run --rm --no-deps -e PERSONAL_OS_AUTO_MIGRATE=0 app python -m app.modules.database.legacy_adoption $(if $(filter 1,$(APPLY)),--apply,)

# Read-only; does not rebuild indexes or acknowledge a library change.
db-collation-check:
	$(COMPOSE) run --rm --no-deps -e PERSONAL_OS_AUTO_MIGRATE=0 app python -m app.modules.database.collation
