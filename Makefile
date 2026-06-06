.PHONY: test test-unit test-all test-integration lint \
        dashboard-push terraform-plan terraform-destroy \
        go-test-compile go-test-bq go-test-idempotency

# ---------------------------------------------------------------------------
# Python tests
# ---------------------------------------------------------------------------

test-unit:
	pytest tests/ -v -m "not integration"

test-all:
	pytest tests/ -v

test-integration:
	pytest tests/ -v -m integration --bq-project ai-trading-prod

test-cov:
	pytest tests/ -v --cov=src --cov-report=term-missing --cov-report=html

# ---------------------------------------------------------------------------
# Linting and type checking
# ---------------------------------------------------------------------------

lint:
	ruff check src/ tests/
	mypy src/ --ignore-missing-imports

fmt:
	ruff format src/ tests/

# ---------------------------------------------------------------------------
# Terraform
# ---------------------------------------------------------------------------

terraform-init:
	cd terraform && terraform init

terraform-plan:
	cd terraform && terraform init && terraform plan -var="project_id=ai-trading-prod"

terraform-apply:
	cd terraform && terraform init && terraform apply -var="project_id=ai-trading-prod" -auto-approve

terraform-destroy:
	cd terraform && terraform destroy -var="project_id=ai-trading-prod" -auto-approve

# ---------------------------------------------------------------------------
# Go / Terratest
# ---------------------------------------------------------------------------

go-test-compile:
	cd terraform/tests && go build ./...

go-test-bq:
	cd terraform/tests && go test -run TestBQDatasetProvisioned -v -timeout 30m

go-test-idempotency:
	cd terraform/tests && go test -run TestTerraformIdempotency -v -timeout 30m

go-test-all:
	cd terraform/tests && go test -v -timeout 30m

# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------

dashboard-push:
	gcloud monitoring dashboards create \
		--config-from-file=monitoring/dashboards/data_platform.json \
		--project=ai-trading-prod
