.PHONY: install test demo ingest eval api up down
install:          ## install dev deps (engine itself is stdlib-only)
	pip install -r requirements-dev.txt
test:             ## run the test suite (17 tests)
	pytest -q
demo:             ## end-to-end offline demo over the fixtures corpus
	python scripts/demo.py fixtures/sample_docs
ingest:           ## batch-load the real mock corpus
	cd services/ai-knowledge-service/ingestion && PYTHONPATH=../../../libs python cli.py --path sample_docs
eval:             ## run the accuracy golden set
	PYTHONPATH=libs python services/ai-admin-service/eval/run_eval.py --docs fixtures/sample_docs --golden fixtures/golden.jsonl
api:              ## run the API gateway locally (dev auth)
	PYTHONPATH=libs:services/ai-assistant-api AUTH_MODE=dev uvicorn app.main:app --app-dir services/ai-assistant-api --port 8000
up:               ## full containerised stack
	docker compose up --build -d
down:
	docker compose down
