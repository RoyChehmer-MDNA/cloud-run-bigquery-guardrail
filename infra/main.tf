terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "api" {
  for_each           = toset(["run.googleapis.com", "bigquery.googleapis.com", "iam.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "guardrail" {
  account_id   = "bq-agent-guardrail"
  display_name = "BigQuery Agent Guardrail"
  description  = "Cloud Run identity for semantic-layer query execution"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_member" "query_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.guardrail.email}"
}

# Add an ACL entry without replacing existing authorized-view entries.
resource "google_bigquery_dataset_access" "semantic_reader" {
  project       = var.data_project_id
  dataset_id    = var.semantic_dataset
  role          = "READER"
  user_by_email = google_service_account.guardrail.email
  depends_on    = [google_project_service.api]
}

resource "google_service_account_iam_member" "deployer" {
  service_account_id = google_service_account.guardrail.name
  role               = "roles/iam.serviceAccountUser"
  member             = var.deployer_member
}

resource "google_cloud_run_v2_service" "guardrail" {
  name                = "bq-agent-guardrail"
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = false

  template {
    service_account = google_service_account.guardrail.email
    timeout         = "120s"
    scaling {
      max_instance_count = 3
    }
    containers {
      image = var.image
      ports {
        container_port = 8080
      }
      dynamic "env" {
        for_each = {
          GOOGLE_CLOUD_PROJECT = var.project_id
          BQ_DATA_PROJECT      = var.data_project_id
          BQ_SEMANTIC_DATASET   = var.semantic_dataset
          BQ_LOCATION          = var.bq_location
          BQ_MAX_BYTES_BILLED   = "1000000000"
          BQ_MAX_ROWS           = "100"
          BQ_TIMEOUT_SECONDS   = "30"
        }
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [
    google_project_service.api, google_project_iam_member.query_jobs,
    google_bigquery_dataset_access.semantic_reader,
    google_service_account_iam_member.deployer
  ]
}

resource "google_cloud_run_v2_service_iam_member" "agent" {
  project  = var.project_id
  location = google_cloud_run_v2_service.guardrail.location
  name     = google_cloud_run_v2_service.guardrail.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.agent_service_account_email}"
}

output "service_url" {
  value = google_cloud_run_v2_service.guardrail.uri
}

output "runtime_service_account" {
  value = google_service_account.guardrail.email
}
