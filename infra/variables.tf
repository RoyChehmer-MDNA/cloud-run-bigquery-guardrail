variable "project_id" {
  type        = string
  description = "Cloud Run and BigQuery job billing project."
}
variable "data_project_id" {
  type        = string
  description = "Project containing the existing semantic dataset."
}
variable "semantic_dataset" {
  type    = string
  default = "semantic_layer"
}
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "bq_location" {
  type        = string
  description = "Actual BigQuery dataset location, e.g. EU."
}
variable "image" {
  type        = string
  description = "Previously built container image URL, preferably pinned by digest."
}
variable "agent_service_account_email" {
  type        = string
  description = "Existing ADK runtime service account, separate from the guardrail identity."
  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.iam\\.gserviceaccount\\.com$", var.agent_service_account_email))
    error_message = "Provide a service account email."
  }
}
variable "deployer_member" {
  type        = string
  description = "Deployment principal, including user: or serviceAccount: prefix."
  validation {
    condition     = can(regex("^(user|serviceAccount):[^@]+@[^@]+$", var.deployer_member))
    error_message = "Provide a specific deployment principal."
  }
}
