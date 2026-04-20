.PHONY: install dev check-server test test-fast lint lint-fix demo cli cli-sample auth-local auth-check vertex-check docker-build docker-up docker-down ingest-sample ingest-goals summary chat reset clean release-dry release-local version-current changelog-preview setup-commit-template

install:
	uv sync

dev:
	uv run uvicorn src.api.main:app --reload --port 8000 --log-level info

demo:
	uv run python3 scripts/demo.py

cli:
	uv run python3 scripts/cli.py

cli-sample:
	uv run python3 scripts/cli.py \
	  --csv data/samples/sample_bank_statement.csv \
	  --goals data/samples/investment_goals.csv \
	  --account "HDFC Savings"

test:
	uv run pytest tests/ -v --tb=short

test-fast:
	uv run pytest tests/ -v --tb=short -x -q

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

lint-fix:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

# ── Vertex AI auth helpers ─────────────────────────────────────────────────────
auth-local:
	gcloud auth application-default login
	@echo "ADC configured — you can now run make dev"

auth-check:
	uv run python3 -c "from dotenv import load_dotenv; load_dotenv(); import google.auth; creds, project = google.auth.default(); print('Project:', project)"

vertex-check:
	uv run python3 -c "from dotenv import load_dotenv; load_dotenv(); from src.llm import get_reasoning_llm; llm = get_reasoning_llm(); resp = llm.invoke('Say hello in one word'); print('Vertex AI:', resp.content)"

# ── Docker ─────────────────────────────────────────────────────────────────────
docker-build:
	docker build -t finance-agent:latest .

docker-up:
	docker-compose up --build

docker-down:
	docker-compose down

check-server:
	@curl -sf http://localhost:8000/health > /dev/null || (echo "\nERROR: API server is not running. Start it first with:\n  make dev\n" && exit 1)

# ── API helpers ────────────────────────────────────────────────────────────────
ingest-sample: check-server
	curl -s -X POST http://localhost:8000/ingest/csv \
	  -F "file=@data/samples/sample_bank_statement.csv" \
	  -F "account_name=HDFC Savings" | uv run python3 -m json.tool

ingest-goals: check-server
	curl -s -X POST http://localhost:8000/ingest/goals \
	  -F "file=@data/samples/investment_goals.csv" | uv run python3 -m json.tool

summary: check-server
	curl -s http://localhost:8000/summary | uv run python3 -m json.tool

chat: check-server
	curl -s -X POST http://localhost:8000/chat \
	  -H "Content-Type: application/json" \
	  -d '{"message": "Give me a complete overview of my finances"}' \
	  | uv run python3 -m json.tool

reset: check-server
	curl -s -X DELETE http://localhost:8000/reset | uv run python3 -m json.tool

# ── Release automation ─────────────────────────────────────────────────────────
# Policy + workflow: docs/RELEASING.md
# All releases are normally performed by .github/workflows/release.yml.
# These targets are for local preview / emergency manual releases only.

version-current:
	@uv run semantic-release version --print-last-released

release-dry:
	@echo "→ Next version (based on commits since last tag):"
	@uv run semantic-release version --print --no-commit --no-tag --no-push --no-vcs-release

changelog-preview:
	@echo "→ Regenerating CHANGELOG.md locally (not committed)..."
	@uv run semantic-release version --no-commit --no-tag --no-push --no-vcs-release --skip-build >/dev/null 2>&1 || true
	@echo "→ Diff of the proposed release changes:"
	@git --no-pager diff CHANGELOG.md pyproject.toml || true
	@echo ""
	@echo "→ Revert preview with: git checkout -- CHANGELOG.md pyproject.toml"

release-local:
	@if [ -z "$$GH_TOKEN" ] && [ -z "$$GITHUB_TOKEN" ]; then \
	  echo "ERROR: GH_TOKEN or GITHUB_TOKEN must be set for a local release."; \
	  echo "  export GH_TOKEN=\$$(gh auth token)"; \
	  exit 1; \
	fi
	@echo "⚠  Running a local release. This commits, tags, and pushes to main."
	uv run semantic-release version
	uv run semantic-release publish

setup-commit-template:
	git config commit.template .gitmessage
	@echo "✓ Commit template enabled. Every 'git commit' will now open .gitmessage."

# ── Cleanup ────────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf data/chroma_db data/gmail_token.json