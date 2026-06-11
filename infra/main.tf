# ============================================================================
# Infrastructure as Code (IaC) for the Care Plan system
# Everything that was clicked together by hand in the Console is
# described here as code instead.
# Run `terraform apply` to build it all in one shot; `terraform destroy` to tear it all down.
# ============================================================================

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
}

# ---- Networking: dedicated VPC (NAT in the public subnets, Lambda/RDS in the private subnets) ----
# Standard production layout: Lambdas in the private subnets reach the internet (to call Claude)
# through the NAT, and are never exposed publicly.
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "careplan-vpc" }
}

data "aws_availability_zones" "available" {
  state = "available"
}

# Public subnets (hosting the NAT) ×2
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index) # 10.0.0.0/24, 10.0.1.0/24
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true
}

# Private subnets (hosting Lambda / RDS) ×2
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 10) # 10.0.10.0/24, 10.0.11.0/24
  availability_zone = data.aws_availability_zones.available.names[count.index]
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
}

# Public route table → IGW
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
}
resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# NAT Gateway (in a public subnet, with an Elastic IP) — lets the private-subnet Lambdas reach the internet to call Claude
resource "aws_eip" "nat" {
  domain = "vpc"
}
resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.igw]
}

# Private route table → NAT (private subnets reach the internet through here)
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat.id
  }
}
resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# Security group: shared by Lambda and RDS. Allows internal 5432 (DB connections) and 443 (SQS endpoint).
resource "aws_security_group" "app" {
  name   = "careplan-sg"
  vpc_id = aws_vpc.main.id

  ingress {
    description = "Postgres within SG"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    self        = true
  }
  ingress {
    description = "HTTPS within SG (for SQS VPC endpoint)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    self        = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# SQS over a VPC Interface Endpoint (private connectivity — cheaper and more secure than going through the NAT)
resource "aws_vpc_endpoint" "sqs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.sqs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.app.id]
  private_dns_enabled = true
}

# DB subnet group for RDS (requires subnets in ≥2 AZs)
resource "aws_db_subnet_group" "main" {
  name       = "careplan-db-subnets"
  subnet_ids = aws_subnet.private[*].id
}

# ---- SQS: main queue + dead-letter queue (DLQ); messages move to the DLQ after 3 failures ----
resource "aws_sqs_queue" "dlq" {
  name = "careplan-dlq"
}

resource "aws_sqs_queue" "main" {
  name = "careplan-queue"
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3 # maxReceiveCount=3
  })
}

# ---- RDS: PostgreSQL database ----
resource "aws_db_instance" "careplan" {
  identifier             = "careplan-db"
  engine                 = "postgres"
  engine_version         = "16.4"        # pgvector is built into RDS PostgreSQL ≥15.2; enable it with CREATE EXTENSION vector (see migration 0002)
  instance_class         = "db.t3.micro" # free-tier / cheapest tier
  allocated_storage      = 20
  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password
  publicly_accessible    = false # in the private subnets, not exposed to the internet
  skip_final_snapshot    = true  # no final snapshot on deletion (for practice purposes)
  vpc_security_group_ids = [aws_security_group.app.id]
  db_subnet_group_name   = aws_db_subnet_group.main.name
}

# ---- IAM: Lambda execution role + permissions (matching the policies attached by hand) ----
resource "aws_iam_role" "lambda" {
  name = "careplan-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# Basic execution permissions (writing CloudWatch logs)
resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
# VPC access permissions (creating network interfaces) — the missing piece behind that CreateNetworkInterface error
resource "aws_iam_role_policy_attachment" "vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}
# SQS send/receive permissions
resource "aws_iam_role_policy_attachment" "sqs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSQSFullAccess"
}

# Environment variables shared across the Lambdas (DB connection info)
locals {
  db_env = {
    # The shared db.py reads DATABASE_URL; on AWS we use the pure-Python pg8000 dialect (no compiled dependencies in Lambda)
    DATABASE_URL = "postgresql+pg8000://${var.db_username}:${var.db_password}@${aws_db_instance.careplan.address}:5432/${var.db_name}"
  }
  vpc_config = {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.app.id]
  }
}

# ---- The 3 Lambdas (code comes from the prebuilt zips) ----
resource "aws_lambda_function" "get_order" {
  function_name    = "get-order"
  filename         = "${path.module}/../aws/get-order.zip"
  source_code_hash = filebase64sha256("${path.module}/../aws/get-order.zip")
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda.arn
  timeout          = 30
  environment { variables = local.db_env }
  vpc_config {
    subnet_ids         = local.vpc_config.subnet_ids
    security_group_ids = local.vpc_config.security_group_ids
  }
}

resource "aws_lambda_function" "create_order" {
  function_name    = "create-order"
  filename         = "${path.module}/../aws/create-order.zip"
  source_code_hash = filebase64sha256("${path.module}/../aws/create-order.zip")
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda.arn
  timeout          = 30
  environment {
    variables = merge(local.db_env, { SQS_QUEUE_URL = aws_sqs_queue.main.url })
  }
  vpc_config {
    subnet_ids         = local.vpc_config.subnet_ids
    security_group_ids = local.vpc_config.security_group_ids
  }
}

resource "aws_lambda_function" "generate_plan" {
  function_name    = "generate-plan"
  filename         = "${path.module}/../aws/generate-plan.zip"
  source_code_hash = filebase64sha256("${path.module}/../aws/generate-plan.zip")
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda.arn
  timeout          = 30
  # Same as the local worker: calls the LLM via llm_service, with the provider chosen by LLM_PROVIDER.
  # RAG: this Lambda runs the shared services.process_care_plan, which does retrieve → embedding.
  # EMBED_PROVIDER defaults to mock (the cloud embedder isn't wired up yet — see the notes in variables.tf);
  # once Voyage is integrated, merge in a VOYAGE_API_KEY = var.voyage_api_key here.
  environment {
    variables = merge(local.db_env, {
      ANTHROPIC_API_KEY = var.anthropic_api_key
      LLM_PROVIDER      = var.llm_provider
      EMBED_PROVIDER    = var.embed_provider
    })
  }
  vpc_config {
    subnet_ids         = local.vpc_config.subnet_ids
    security_group_ids = local.vpc_config.security_group_ids
  }
}

# ---- SQS automatically triggers generate-plan (matching the SQS trigger added by hand) ----
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.main.arn
  function_name    = aws_lambda_function.generate_plan.arn
}

# ---- API Gateway (HTTP API): POST /orders, GET /orders/{id} ----
resource "aws_apigatewayv2_api" "api" {
  name          = "careplan-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "create" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.create_order.invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_integration" "get" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.get_order.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "post_orders" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "POST /orders"
  target    = "integrations/${aws_apigatewayv2_integration.create.id}"
}
resource "aws_apigatewayv2_route" "get_order" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "GET /orders/{id}"
  target    = "integrations/${aws_apigatewayv2_integration.get.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
}

# Allow API Gateway to invoke these two Lambdas
resource "aws_lambda_permission" "create" {
  statement_id  = "AllowAPIGWCreate"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.create_order.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
resource "aws_lambda_permission" "get" {
  statement_id  = "AllowAPIGWGet"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.get_order.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
