# ==================== VARIABLES ====================
variable "hr_admin_username" {
  description = "Admin username for HR Portal"
  type        = string
  default     = "admin"
}

variable "hr_admin_password" {
  description = "Admin password for HR Portal"
  type        = string
  default     = "Innovatech2024!"
  sensitive   = true
}

# ECR REPOSITORY 
resource "aws_ecr_repository" "hr_portal" {
  name                 = "${var.project_name}-hr-portal"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }



  tags = {
    Name = "${var.project_name}-hr-portal-ecr"
  }
}

# ECS CLUSTER 
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-ecs-cluster"
  }
}

# CLOUDWATCH LOG GROUP 
resource "aws_cloudwatch_log_group" "hr_portal" {
  name              = "/ecs/${var.project_name}-hr-portal"
  retention_in_days = 7

  tags = {
    Name = "${var.project_name}-hr-portal-logs"
  }
}

# IAM ROLE FOR ECS TASK EXECUTION 
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-ecs-task-execution-role"
  }
}

# Attach AWS managed policy for ECS task execution
resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# IAM ROLE FOR ECS TASK APPLICATION
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-ecs-task-role"
  }
}

# Policy for DynamoDB access
resource "aws_iam_role_policy" "ecs_task_dynamodb" {
  name = "${var.project_name}-ecs-task-dynamodb-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Scan",
          "dynamodb:Query",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem"
        ]
        Resource = aws_dynamodb_table.employees.arn
      }
    ]
  })
}

# ==================== ECS TASK DEFINITION ====================
resource "aws_ecs_task_definition" "hr_portal" {
  family                   = "${var.project_name}-hr-portal"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256" 
  memory                   = "512" 
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "hr-portal"
      image = "${aws_ecr_repository.hr_portal.repository_url}:latest"

      essential = true

      portMappings = [
        {
          containerPort = 3000
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "DYNAMODB_TABLE"
          value = aws_dynamodb_table.employees.name
        },
        {
          name  = "AWS_REGION"
          value = "eu-central-1"
        },
        {
          name  = "ADMIN_USERNAME"
          value = var.hr_admin_username
        },
        {
          name  = "ADMIN_PASSWORD"
          value = var.hr_admin_password
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.hr_portal.name
          "awslogs-region"        = "eu-central-1"
          "awslogs-stream-prefix" = "ecs"
        }
      }

    }
  ])

  tags = {
    Name = "${var.project_name}-hr-portal-task"
  }
}

# ==================== ECS SERVICE ====================
resource "aws_ecs_service" "hr_portal" {
  name            = "${var.project_name}-hr-portal-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.hr_portal.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.private_web_a.id, aws_subnet.private_web_b.id]
    security_groups  = [aws_security_group.hr_portal.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.hr_portal.arn
    container_name   = "hr-portal"
    container_port   = 3000
  }

  depends_on = [
    aws_lb_listener.http,
    aws_iam_role_policy.ecs_task_dynamodb
  ]

  tags = {
    Name = "${var.project_name}-hr-portal-service"
  }
}

# ==================== OUTPUTS ====================
output "ecr_repository_url" {
  value       = aws_ecr_repository.hr_portal.repository_url
  description = "ECR repository URL for HR Portal Docker image"
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.hr_portal.name
}

output "docker_build_instructions" {
  value = <<-EOT
  
  📦 Build and Push Docker Image to ECR:
  ========================================
  
  1. Login to ECR:
     aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin ${aws_ecr_repository.hr_portal.repository_url}
  
  2. Build Docker image:
     cd hr-portal-app
     docker build -t ${aws_ecr_repository.hr_portal.repository_url}:latest .
  
  3. Push to ECR:
     docker push ${aws_ecr_repository.hr_portal.repository_url}:latest
  
  4. Restart ECS service (force new deployment):
     aws ecs update-service --cluster ${aws_ecs_cluster.main.name} --service ${aws_ecs_service.hr_portal.name} --force-new-deployment --region eu-central-1
  
  EOT
}