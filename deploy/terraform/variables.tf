variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "name" {
  type    = string
  default = "aistack"
}

variable "image_tag" {
  description = "Tag of the api and web images pushed to the ECR repositories."
  type        = string
  default     = "0.1.0"
}

variable "certificate_arn" {
  description = "ACM certificate for the HTTPS listener."
  type        = string
}

variable "public_api_url" {
  description = "Public URL of the gateway (also the OIDC issuer when the mock IdP is used)."
  type        = string
}

variable "public_web_url" {
  type = string
}

variable "desired_count" {
  type    = number
  default = 2
}
