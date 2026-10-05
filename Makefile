.PHONY: install run test smoke browser docker-build docker-up docker-down clean

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q

# 需要服务已启动
smoke:
	python scripts/smoke_test.py

# 浏览器级端到端验证（需 playwright + chromium）
browser:
	python scripts/browser_check.py

docker-build:
	docker compose build

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

clean:
	rm -rf app.db uploads/* logs/* .pytest_cache screenshots_pdf
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
