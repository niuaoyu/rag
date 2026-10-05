.PHONY: install run test smoke docker-build docker-up docker-down clean

install:
pip install -r requirements.txt

run:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
pytest -q

# 需要服务已通过 make run 启动
smoke:
python scripts/smoke_test.py

docker-build:
docker compose build

docker-up:
docker compose up -d

docker-down:
docker compose down

clean:
rm -rf app.db uploads/* logs/* .pytest_cache
find . -name __pycache__ -type d -prune -exec rm -rf {} +

# 端到端 smoke（使用内置示例文档）
smoke-sample:
python scripts/smoke_test.py
