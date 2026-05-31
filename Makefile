.PHONY: up down logs test ingest

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	docker compose run --rm api pytest tests/ -v

ingest:
	docker compose run --rm worker python detect.py --video $$VIDEO
