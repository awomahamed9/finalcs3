# ==================== APPLICATION LOAD BALANCER ====================

# Target Group for HR Portal (ECS Fargate)
resource "aws_lb_target_group" "hr_portal" {
  name        = "${var.project_name}-hr-portal-tg"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"  # Required for Fargate

  health_check {
    enabled             = true
    path                = "/health"
    port                = "3000"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "${var.project_name}-hr-portal-tg"
  }
}

# ECS service automatically registers tasks to target group

# Application Load Balancer
resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public_a.id, aws_subnet.public_b.id]

  enable_deletion_protection = false
  enable_http2               = true

  tags = {
    Name = "${var.project_name}-alb"
  }
}

# HTTP Listener (port 80)
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.hr_portal.arn
  }
}

# ==================== OUTPUTS ====================
output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "ALB DNS name - use this to access HR Portal"
}

output "hr_portal_url" {
  value       = "http://${aws_lb.main.dns_name}"
  description = "HR Portal URL (publicly accessible) - Login required: admin / Innovatech2024!"
}