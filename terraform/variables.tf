variable "project_id" {
  description = "GCP project ID where resources will be provisioned."
  type        = string
  default     = "ai-trading-prod"
}

variable "region" {
  description = "Default GCP region for regional resources."
  type        = string
  default     = "us-central1"
}
