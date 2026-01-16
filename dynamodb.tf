resource "aws_dynamodb_table" "employees" {
  name         = "${var.project_name}-employees"
  billing_mode = "PAY_PER_REQUEST" 
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  # Enables DynamoDB Streams for Lambda trigger
  stream_enabled   = true
  stream_view_type = "NEW_IMAGE" 

  tags = {
    Name = "${var.project_name}-employees-table"
  }
}

# ==================== OUTPUTS ====================
output "dynamodb_table_name" {
  value = aws_dynamodb_table.employees.name
}

output "dynamodb_table_arn" {
  value = aws_dynamodb_table.employees.arn
}

output "dynamodb_stream_arn" {
  value = aws_dynamodb_table.employees.stream_arn
}

