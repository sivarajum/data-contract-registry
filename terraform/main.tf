terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# BigQuery dataset for schema registry metadata and audit logs
# ---------------------------------------------------------------------------

resource "google_bigquery_dataset" "contracts" {
  project                    = var.project_id
  dataset_id                 = "poc11_contracts"
  friendly_name              = "POC-11 Data Contract Registry"
  description                = "Schema registry metadata, compatibility audit logs, and contract breach events for POC-11."
  location                   = "US"
  delete_contents_on_destroy = false

  labels = {
    env = "dev"
    poc = "poc11"
  }
}

# ---------------------------------------------------------------------------
# Pub/Sub: contract violation event pipeline
# ---------------------------------------------------------------------------

resource "google_pubsub_topic" "contract_violations" {
  project = var.project_id
  name    = "poc11-contract-violations"

  labels = {
    env = "dev"
    poc = "poc11"
  }
}

resource "google_pubsub_topic" "contract_violations_dlq" {
  project = var.project_id
  name    = "poc11-contract-violations-dlq"

  labels = {
    env = "dev"
    poc = "poc11"
  }
}

resource "google_pubsub_subscription" "contract_violations_sub" {
  project = var.project_id
  name    = "poc11-contract-violations-sub"
  topic   = google_pubsub_topic.contract_violations.name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s" # 7 days
  retain_acked_messages      = false

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.contract_violations_dlq.id
    max_delivery_attempts = 5
  }

  labels = {
    env = "dev"
    poc = "poc11"
  }
}

# ---------------------------------------------------------------------------
# Service account for the contract registry process
# ---------------------------------------------------------------------------

resource "google_service_account" "contracts_sa" {
  project      = var.project_id
  account_id   = "poc11-contracts-sa"
  display_name = "POC-11 Contracts Service Account"
  description  = "Used by the in-process schema registry to write audit events to BQ and publish violations to Pub/Sub."
}

# ---------------------------------------------------------------------------
# IAM bindings
# ---------------------------------------------------------------------------

resource "google_bigquery_dataset_iam_binding" "editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.contracts.dataset_id
  role       = "roles/bigquery.dataEditor"

  members = [
    "serviceAccount:${google_service_account.contracts_sa.email}",
  ]
}

resource "google_pubsub_topic_iam_binding" "violations_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.contract_violations.name
  role    = "roles/pubsub.publisher"

  members = [
    "serviceAccount:${google_service_account.contracts_sa.email}",
  ]
}

resource "google_pubsub_topic_iam_binding" "dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.contract_violations_dlq.name
  role    = "roles/pubsub.publisher"

  members = [
    "serviceAccount:${google_service_account.contracts_sa.email}",
  ]
}
