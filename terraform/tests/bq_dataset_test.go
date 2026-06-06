package test

import (
	"testing"

	"github.com/gruntwork-io/terratest/modules/terraform"
	"github.com/stretchr/testify/assert"
)

// TestBQDatasetProvisioned provisions the full terraform stack, asserts that all
// outputs have the expected values, then tears everything down.
//
// Prerequisites:
//   - GOOGLE_APPLICATION_CREDENTIALS or ADC configured
//   - The service account must have BigQuery, Pub/Sub, and IAM permissions in ai-trading-prod
//
// Run with:
//
//	cd terraform/tests && go test -run TestBQDatasetProvisioned -v -timeout 30m
func TestBQDatasetProvisioned(t *testing.T) {
	t.Parallel()

	terraformOptions := terraform.WithDefaultRetryableErrors(t, &terraform.Options{
		TerraformDir: "../",
		Vars: map[string]interface{}{
			"project_id": "ai-trading-prod",
		},
	})

	// Always destroy after the test, regardless of pass/fail.
	defer terraform.Destroy(t, terraformOptions)

	terraform.InitAndApply(t, terraformOptions)

	// Assert BigQuery dataset output.
	datasetID := terraform.Output(t, terraformOptions, "dataset_id")
	assert.Equal(t, "poc11_contracts", datasetID, "BQ dataset_id must match the expected value")

	// Assert Pub/Sub topic output.
	topicName := terraform.Output(t, terraformOptions, "topic_name")
	assert.Equal(t, "poc11-contract-violations", topicName, "Pub/Sub topic name must match")

	// Assert DLQ topic output.
	dlqTopicName := terraform.Output(t, terraformOptions, "dlq_topic_name")
	assert.Equal(t, "poc11-contract-violations-dlq", dlqTopicName, "DLQ topic name must match")

	// Assert subscription output.
	subscriptionName := terraform.Output(t, terraformOptions, "subscription_name")
	assert.Equal(t, "poc11-contract-violations-sub", subscriptionName, "Subscription name must match")

	// Assert service account email contains the expected account-id fragment.
	saEmail := terraform.Output(t, terraformOptions, "sa_email")
	assert.Contains(t, saEmail, "poc11-contracts-sa", "SA email must contain the account-id fragment")
	assert.Contains(t, saEmail, "iam.gserviceaccount.com", "SA email must be a valid GCP IAM email")
}
