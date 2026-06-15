.PHONY: up down logs migrate lint test shell

up:
	docker compose up --build -d
	@echo "Waiting for services..."
	@sleep 5
	docker compose exec api alembic upgrade head
	@echo ""
	@echo "✅ DocFlow is running:"
	@echo "   API:    http://localhost:8000"
	@echo "   Docs:   http://localhost:8000/docs"
	@echo "   Flower: http://localhost:5555"

down:
	docker compose down

logs:
	docker compose logs -f api worker

migrate:
	docker compose exec api alembic upgrade head

lint:
	ruff check app tests

lint-fix:
	ruff check --fix app tests

test:
	pip install aiosqlite pytest-asyncio pytest-mock httpx --break-system-packages -q 2>/dev/null; \
	pytest tests/ -v

smoke:
	@echo "Testing POST /files..."
	curl -s -X POST http://localhost:8000/files \
	  -F "files=@samples/01_реестр_СтройМонтаж.xlsx" | python3 -m json.tool
	@echo ""
	@echo "Testing GET /stats..."
	curl -s http://localhost:8000/stats | python3 -m json.tool
