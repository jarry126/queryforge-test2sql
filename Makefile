.PHONY: help install infra-up infra-down migrate ingest run smoke test lint fmt check-config rate-limit-test

help:
	@echo "install     安装依赖 (pip install -e '.[eval,dev]')"
	@echo "loadtest    100 QPS 开环压测 /query，输出时延分位"
	@echo "rate-limit-test 验证 /query 限流是否返回 429"
	@echo "infra-up    启动 postgres(pgvector+pg_jieba)/redis/prometheus/grafana"
	@echo "infra-down  停止基础设施"
	@echo "migrate     执行 alembic 迁移（建扩展与表）"
	@echo "ingest      把 CSpider schema 灌进 pgvector + 注册 sqlite 库"
	@echo "run         本地启动 API (uvicorn --reload)"
	@echo "smoke       对 CSpider dev 抽样做端到端冒烟"
	@echo "test        运行 pytest"
	@echo "lint/fmt    ruff 检查 / 格式化"
	@echo "check-config 校验当前环境配置"

install:
	pip install -e ".[eval,dev]"

infra-up:
	docker compose up -d postgres redis prometheus grafana

infra-down:
	docker compose down

langfuse-up:
	docker compose -f docker-compose.langfuse.yml up -d
	@echo "Langfuse 启动中 → http://localhost:3000 （首次需注册并建项目，拿到 key 填进 .env）"

langfuse-down:
	docker compose -f docker-compose.langfuse.yml down

migrate:
	alembic upgrade head

ingest:
	python -m eval.ingest_cspider

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

smoke:
	python -m scripts.smoke_query --limit 20

loadtest:
	python -m scripts.loadtest --rps 100 --duration 30

rate-limit-test:
	python -m scripts.rate_limit_test --requests 20 --concurrency 20

test:
	pytest -q

check-config:
	python -m scripts.check_config

lint:
	ruff check app eval scripts tests

fmt:
	ruff format app eval scripts tests
