# After apply completes, Terraform prints these values
output "api_url" {
  description = "Public API Gateway address (POST /orders, GET /orders/{id})"
  value       = aws_apigatewayv2_api.api.api_endpoint
}

output "rds_endpoint" {
  value = aws_db_instance.careplan.address
}

output "queue_url" {
  value = aws_sqs_queue.main.url
}
