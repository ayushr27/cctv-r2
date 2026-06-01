.PHONY: up down logs test ingest classify

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

# Staff classification pass over the merged event log (Phase 5).
# Overwrites events.jsonl with the classified superset so the API picks it up.
classify:
	docker compose run --rm worker python classify.py \
		--in /events/events.jsonl --out /events/events.classified.jsonl
	cp events/events.classified.jsonl events/events.jsonl
