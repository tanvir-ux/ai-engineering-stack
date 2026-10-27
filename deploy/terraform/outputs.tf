output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "ecr_repositories" {
  value = { for k, r in aws_ecr_repository.images : k => r.repository_url }
}

output "secret_names" {
  description = "Fill these in Secrets Manager. Terraform never sees the values."
  value       = [for s in aws_secretsmanager_secret.llm : s.name]
}
