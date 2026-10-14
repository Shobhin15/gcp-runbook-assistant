output "workload_identity_provider" {
  description = "Set as the GCP_WIF_PROVIDER GitHub variable"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  description = "Set as the GCP_DEPLOYER_SA GitHub variable"
  value       = google_service_account.deployer.email
}

output "runtime_service_account" {
  description = "Set as the GCP_RUNTIME_SA GitHub variable"
  value       = google_service_account.runtime.email
}
