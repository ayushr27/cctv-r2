.PHONY: up down logs test test-worker ingest classify

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# API + business-logic tests (run in the api image). The worker geometry tests
# need shapely (a worker dep absent from the api image) and a separate sys.path
# scope, so they run via `make test-worker`. CI runs both — see ci.yml.
test:
	docker compose run --rm --no-deps \
		-v "$(PWD)/tests:/app/tests:ro" -v "$(PWD)/conftest.py:/app/conftest.py:ro" \
		-v "$(PWD)/pytest.ini:/app/pytest.ini:ro" \
		-e PYTHONPATH=/app/api api \
		python -m pytest tests/test_api.py tests/test_pos_join.py \
		tests/test_anomaly.py tests/test_smoke.py \
		--cov=services --cov-report=term-missing --cov-fail-under=70

test-worker:
	docker compose run --rm --no-deps --entrypoint sh \
		-v "$(PWD):/repo" -w /repo -e PYTHONPATH=/repo/worker worker -lc \
		"pip install --quiet pytest==8.3.3 pytest-cov==5.0.0 && \
		 python -m pytest tests/test_line_crossing.py tests/test_zones.py tests/test_reentry.py tests/test_classify.py \
		 --cov=events --cov=schemas --cov=classify --cov-report=term-missing --cov-fail-under=70"

ingest:
	docker compose run --rm worker python detect.py --video $$VIDEO

# Staff classification pass over the merged event log (Phase 5).
# Overwrites events.jsonl with the classified superset so the API picks it up.
classify:
	docker compose run --rm worker python classify.py \
		--in /events/events.jsonl --out /events/events.classified.jsonl
	cp events/events.classified.jsonl events/events.jsonl
