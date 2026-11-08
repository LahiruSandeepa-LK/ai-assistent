.PHONY: dev up down ingest test lint fmt
dev:            ## run dev stack (AUTH_MODE=dev, hot reload)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
up:             ## run full stack with Keycloak
	docker compose up --build -d
down:
	docker compose down
ingest:         ## batch-load the mock corpus into Pinecone
	docker compose run --rm ingest python cli.py --path services/ingestion/sample_docs
test:
	pytest -q
lint:
	ruff check . && mypy libs services
fmt:
	ruff format .
