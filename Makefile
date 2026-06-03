.PHONY: up down migrate seed test build logs

# Start all services
up:
	docker-compose up -d

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
