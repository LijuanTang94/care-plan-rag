# Variables: values that aren't hardcoded live here (same idea as using environment variables in code)
variable "region" {
  default = "us-east-1"
}

variable "db_password" {
  description = "RDS master password"
  type        = string
  sensitive   = true # marked sensitive so Terraform won't print it in logs
}

variable "db_name" {
  default = "careplan"
}

variable "db_username" {
  default = "postgres"
}

variable "anthropic_api_key" {
  description = "Claude API key (used by the generate-plan Lambda to call the LLM)"
  type        = string
  sensitive   = true
}

variable "llm_provider" {
  description = "Which LLM to use: claude = real, mock = fake (same switch as the local setup)"
  default     = "claude"
}

# Embedding provider for RAG. Locally we use fastembed (an ONNX model, ~100MB+), but Lambda has a 250MB
# unzipped limit and loading the model on every cold start is slow — in production we use a cloud embedding
# API (Voyage/OpenAI; Anthropic has no embedding model).
# Defaults to mock: until the cloud embedder (VoyageEmbedder) is written into embedding_service.py, RAG on the AWS side won't produce real scores.
variable "embed_provider" {
  description = "RAG embedding: mock (placeholder) / voyage / openai (cloud API, suited to Lambda)"
  default     = "mock"
}
