package test

import (
	"testing"

	"github.com/gruntwork-io/terratest/modules/terraform"
	"github.com/stretchr/testify/assert"
)

// TestTerraformIdempotency verifies that applying Terraform twice produces no changes.
//
// Terraform plan exit codes:
//   - 0: No changes (infrastructure matches configuration) — expected on second run
//   - 1: Error
//   - 2: Changes present (infrastructure drift detected) — this test fails if seen
//
// Why this matters: Idempotency is a hard requirement for production Terraform modules.
// Non-idempotent modules cause phantom diffs on every CI run, silently overwrite live
// resources, and make it impossible to detect genuine drift.
//
// Run with:
//
//	cd terraform/tests && go test -run TestTerraformIdempotency -v -timeout 30m
func TestTerraformIdempotency(t *testing.T) {
	t.Parallel()

	terraformOptions := terraform.WithDefaultRetryableErrors(t, &terraform.Options{
		TerraformDir: "../",
		Vars: map[string]interface{}{
			"project_id": "ai-trading-prod",
		},
	})

	// Always tear down after the test.
	defer terraform.Destroy(t, terraformOptions)

	// First apply: provision all resources.
	terraform.InitAndApply(t, terraformOptions)

	// Second plan: must show zero changes (exit code 0).
	// Exit code 2 means terraform detected a diff — idempotency failure.
	exitCode := terraform.PlanWithExitCode(t, terraformOptions)
	assert.Equal(
		t,
		0,
		exitCode,
		"Second terraform plan must return exit code 0 (no changes). "+
			"Exit code 2 indicates non-idempotent resource definitions.",
	)
}
