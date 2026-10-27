terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Remote state is intentionally not configured in this sketch. Add an S3 backend with
  # DynamoDB locking before using it for real.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project = "ai-engineering-stack"
      managed = "terraform"
    }
  }
}
