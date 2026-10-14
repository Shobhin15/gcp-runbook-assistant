variable "project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry, and Vertex AI"
  type        = string
  default     = "us-central1"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as owner/name"
  type        = string
  default     = "Shobhin15/gcp-runbook-assistant"
}
