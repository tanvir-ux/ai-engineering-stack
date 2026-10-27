# Sketch of an AWS deployment: ECR, ECS Fargate behind an ALB, Secrets Manager and CloudWatch.
# It is validated with `terraform validate` only. It has not been applied to an AWS account.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_ecr_repository" "images" {
  for_each             = toset(["api", "web"])
  name                 = "${var.name}-${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.name}"
  retention_in_days = 30
}

# Secret containers only. Values are written out of band (console, CLI or CI), never by Terraform.
resource "aws_secretsmanager_secret" "llm" {
  for_each = toset(["OPENAI_API_KEY", "GEMINI_API_KEY", "PINECONE_API_KEY"])
  name     = "${var.name}/${each.key}"
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  vpc_id      = data.aws_vpc.default.id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "tasks" {
  name_prefix = "${var.name}-tasks-"
  vpc_id      = data.aws_vpc.default.id
  ingress {
    from_port       = 8000
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  # Tasks of the same service reach each other (gateway to MCP).
  ingress {
    from_port = 8001
    to_port   = 8001
    protocol  = "tcp"
    self      = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb" "this" {
  name                       = var.name
  load_balancer_type         = "application"
  subnets                    = data.aws_subnets.default.ids
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  name        = "${var.name}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = data.aws_vpc.default.id
  health_check {
    path    = "/ready"
    matcher = "200"
  }
}

resource "aws_lb_target_group" "web" {
  name        = "${var.name}-web"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = data.aws_vpc.default.id
  health_check {
    path = "/"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
  condition {
    host_header {
      values = [replace(var.public_api_url, "https://", "")]
    }
  }
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for s in aws_secretsmanager_secret.llm : s.arn]
  }
}

resource "aws_iam_role_policy" "read_secrets" {
  name   = "read-llm-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

resource "aws_ecs_cluster" "this" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

locals {
  common_env = [
    { name = "AISTACK_OIDC_ISSUER", value = "${var.public_api_url}/idp" },
    { name = "AISTACK_OIDC_JWKS_URL", value = "http://127.0.0.1:8000/idp/jwks.json" },
    { name = "AISTACK_MCP_URL", value = "http://127.0.0.1:8001/mcp/" },
    { name = "AISTACK_CORS_ORIGINS", value = jsonencode([var.public_web_url]) },
    { name = "AISTACK_OIDC_REDIRECT_PREFIXES", value = jsonencode([var.public_web_url]) },
  ]
  log_config = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.app.name
      awslogs-region        = var.region
      awslogs-stream-prefix = "app"
    }
  }
}

# One task, three containers. The gateway and MCP server share a network namespace, so they
# talk over localhost and the MCP port is never exposed.
resource "aws_ecs_task_definition" "app" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([
    {
      name                   = "api"
      image                  = "${aws_ecr_repository.images["api"].repository_url}:${var.image_tag}"
      essential              = true
      portMappings           = [{ containerPort = 8000 }]
      environment            = local.common_env
      secrets                = [for k, s in aws_secretsmanager_secret.llm : { name = k, valueFrom = s.arn }]
      logConfiguration       = local.log_config
      readonlyRootFilesystem = false
    },
    {
      name             = "mcp"
      image            = "${aws_ecr_repository.images["api"].repository_url}:${var.image_tag}"
      essential        = true
      command          = ["aistack", "mcp", "--transport", "http", "--host", "127.0.0.1", "--port", "8001"]
      environment      = local.common_env
      logConfiguration = local.log_config
    },
    {
      name             = "web"
      image            = "${aws_ecr_repository.images["web"].repository_url}:${var.image_tag}"
      essential        = true
      portMappings     = [{ containerPort = 8080 }]
      logConfiguration = local.log_config
    },
  ])
}

resource "aws_ecs_service" "app" {
  name            = var.name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8080
  }
  depends_on = [aws_lb_listener.https]
}
