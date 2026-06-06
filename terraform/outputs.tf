output "dataset_id" {
  description = "BigQuery dataset ID for contract metadata."
  value       = google_bigquery_dataset.contracts.dataset_id
}

output "topic_name" {
  description = "Pub/Sub topic name for contract violation events."
  value       = google_pubsub_topic.contract_violations.name
}

output "dlq_topic_name" {
  description = "Pub/Sub dead-letter topic name."
  value       = google_pubsub_topic.contract_violations_dlq.name
}

output "subscription_name" {
  description = "Pub/Sub subscription name."
  value       = google_pubsub_subscription.contract_violations_sub.name
}

output "sa_email" {
  description = "Service account email for the contract registry process."
  value       = google_service_account.contracts_sa.email
}
