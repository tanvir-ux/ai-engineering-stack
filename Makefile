SHELL := /bin/bash
PY ?= python

.PHONY: help install data eval test test-fast lint typecheck security frontend-test frontend-build \
        validate-bundle k8s-render k8s-validate tf-validate check dev-stack record smoke

help:  ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

install:  ## Create .venv and install everything (uv required)
	uv venv .venv && . .venv/bin/activate && uv pip install -e ".[dev,spark]" && cd frontend && npm ci

data:  ## Rebuild the gold tables with PySpark and Delta (needs Java)
	aistack data

eval:  ## Retrieval eval and agent eval. Rewrites docs/EVAL_REPORT.md and docs/AGENT_EVAL.md
	$(PY) -m aistack.eval.rag_eval
	$(PY) -m aistack.eval.agent_eval

test:  ## All Python tests (includes the Spark tests; needs Java) and the front-end tests
	$(PY) -m pytest -q
	cd frontend && npm test

test-fast:  ## Python tests without Spark
	$(PY) -m pytest -q -m "not spark"

lint:  ## ruff
	ruff check . && ruff format --check .

typecheck:  ## mypy (strict) and the TypeScript compiler
	mypy src/aistack
	cd frontend && npx tsc --noEmit

security:  ## bandit on our code, pip-audit on dependencies
	bandit -q -r src -ll
	pip-audit --skip-editable --progress-spinner off

frontend-build:  ## Production build of the web app
	cd frontend && npm run build

validate-bundle:  ## Offline `databricks bundle validate` against a local stub workspace
	$(PY) scripts/validate_bundle.py

k8s-render:  ## Re-render deploy/k8s/aistack.yaml from the Helm chart
	helm template aistack deploy/helm/aistack > deploy/k8s/aistack.yaml

k8s-validate:  ## helm lint + kubeconform on the rendered manifests
	helm lint deploy/helm/aistack
	helm template aistack deploy/helm/aistack | kubeconform -strict -summary -kubernetes-version 1.30.0

tf-validate:  ## terraform validate (no backend, no credentials)
	cd deploy/terraform && terraform init -backend=false -input=false && terraform validate

check: lint typecheck test security  ## Everything CI runs for Python and TypeScript

dev-stack:  ## Gateway on :8010 and MCP on :8001, using the local fake model
	AISTACK_RATE_LIMIT_PER_MINUTE=300 AISTACK_OIDC_ISSUER=http://localhost:8010/idp \
	  AISTACK_IDP_KEY_FILE=.dev/idp_key.pem aistack mcp --transport http --port 8001 & \
	AISTACK_RATE_LIMIT_PER_MINUTE=300 AISTACK_OIDC_ISSUER=http://localhost:8010/idp \
	  AISTACK_IDP_KEY_FILE=.dev/idp_key.pem AISTACK_MCP_URL=http://127.0.0.1:8001/mcp/ \
	  aistack serve --port 8010

record:  ## Re-record the demo sessions from a running dev stack
	$(PY) scripts/record_runs.py --base http://localhost:8010 --out frontend/public/recordings

smoke:  ## End-to-end smoke test against a running stack
	$(PY) scripts/compose_smoke.py --base http://localhost:8010
