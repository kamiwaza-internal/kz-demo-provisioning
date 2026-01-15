.PHONY: help install dev-install run worker redis db-init test clean format lint

help:
	@echo "AWS EC2 Provisioning Service - Make Commands"
	@echo ""
	@echo "  make install       - Install production dependencies"
	@echo "  make dev-install   - Install all dependencies including dev tools"
	@echo "  make run           - Run FastAPI web server"
	@echo "  make worker        - Run Celery worker"
	@echo "  make redis         - Run Redis in Docker (for development)"
	@echo "  make db-init       - Initialize database"
	@echo "  make test          - Run tests"
	@echo "  make clean         - Clean temporary files"
	@echo "  make format        - Format code with black"
	@echo "  make lint          - Lint code with flake8"
	@echo ""

install:
	pip install -r requirements.txt

dev-install:
	pip install -r requirements.txt
	pip install black flake8 isort

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	celery -A worker.celery_app worker --loglevel=info

redis:
	@echo "Starting Redis in Docker..."
	docker run -d --name kz-redis -p 6379:6379 redis:7-alpine || docker start kz-redis
	@echo "Redis running on localhost:6379"

db-init:
	python -c "from app.database import init_db; init_db(); print('Database initialized')"

test:
	pytest tests/ -v

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache
	rm -f app.db
	rm -rf jobs_workdir
	rm -rf uploads

format:
	black app/ worker/ tests/
	isort app/ worker/ tests/

lint:
	flake8 app/ worker/ --max-line-length=120 --ignore=E203,W503

# Development helpers
.PHONY: dev stop-redis

dev:
	@echo "Starting development environment..."
	@make redis
	@echo ""
	@echo "Run these commands in separate terminals:"
	@echo "  1. make run     (Web server)"
	@echo "  2. make worker  (Background worker)"
	@echo ""

stop-redis:
	docker stop kz-redis || true
	docker rm kz-redis || true
