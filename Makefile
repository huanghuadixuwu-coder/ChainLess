.PHONY: up down debug-up tls-up migrate seed test build logs backup restore

# Start all services
up:
	docker-compose up -d

debug-up:
	docker-compose -f docker-compose.yml -f docker-compose.debug.yml up -d

tls-up:
	docker-compose -f docker-compose.yml -f docker-compose.tls.yml up -d

# Stop all services
down:
	docker-compose down

# Run database migrations
migrate:
	docker-compose exec backend alembic upgrade head

# Seed the database
seed:
	docker-compose exec -T backend python scripts/seed.py

# Run tests
test:
	docker-compose exec backend pytest

# Build images (no cache)
build:
	docker-compose build --no-cache

# Tail logs
logs:
	docker-compose logs -f

# Create a PostgreSQL backup in the /backups volume
backup:
	docker-compose exec backend ./scripts/backup.sh

# Restore a backup: make restore FILE=/backups/chainless-YYYYmmdd-HHMMSS.sql
restore:
	test -n "$(FILE)"
	docker-compose run --rm backend ./scripts/restore.sh "$(FILE)"
