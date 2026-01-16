# ==================== WINDOWS AUTOMATION SERVER ====================

# Windows Server 2022 AMI
data "aws_ami" "windows_2022" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Windows_Server-2022-English-Full-Base-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# IAM Role for Automation Server
resource "aws_iam_role" "ad_automation" {
  name = "${var.project_name}-ad-automation-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })

  tags = {
    Name = "${var.project_name}-ad-automation-role"
  }
}

# Permissions for Secrets Manager and Directory Service
resource "aws_iam_role_policy" "ad_automation_permissions" {
  name = "${var.project_name}-ad-automation-permissions"
  role = aws_iam_role.ad_automation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "ds:DescribeDirectories"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Subscribe",
          "sns:Receive",
          "sqs:*"
        ]
        Resource = "*"
      }
    ]
  })
}

# SSM for remote management
resource "aws_iam_role_policy_attachment" "ad_automation_ssm" {
  role       = aws_iam_role.ad_automation.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Instance Profile
resource "aws_iam_instance_profile" "ad_automation" {
  name = "${var.project_name}-ad-automation-profile"
  role = aws_iam_role.ad_automation.name
}

# Security Group for RDP Access
resource "aws_security_group" "ad_automation" {
  name        = "${var.project_name}-ad-automation-sg"
  description = "RDP access for AD automation server"
  vpc_id      = aws_vpc.main.id

  # RDP from VPN only
  ingress {
    description     = "RDP from VPN"
    from_port       = 3389
    to_port         = 3389
    protocol        = "tcp"
    security_groups = [aws_security_group.openvpn.id]
  }

  # Allow all outbound
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ad-automation-sg"
  }
}

# SNS Topic for Lambda to Windows Communication
resource "aws_sns_topic" "ad_user_provisioning" {
  name = "${var.project_name}-ad-user-provisioning"

  tags = {
    Name = "${var.project_name}-ad-user-provisioning-topic"
  }
}

# SQS Queue for SNS messages and this is what Windows will poll
resource "aws_sqs_queue" "ad_user_provisioning" {
  name                       = "${var.project_name}-ad-user-provisioning-queue"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 86400 

  tags = {
    Name = "${var.project_name}-ad-user-provisioning-queue"
  }
}

# Subscribe SQS to SNS
resource "aws_sns_topic_subscription" "ad_user_provisioning" {
  topic_arn = aws_sns_topic.ad_user_provisioning.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.ad_user_provisioning.arn
}

# SQS Queue Policy so this will allow SNS to send messages to sqs
resource "aws_sqs_queue_policy" "ad_user_provisioning" {
  queue_url = aws_sqs_queue.ad_user_provisioning.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.ad_user_provisioning.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_sns_topic.ad_user_provisioning.arn
        }
      }
    }]
  })
}

# Windows Automation EC2
resource "aws_instance" "ad_automation" {
  ami           = data.aws_ami.windows_2022.id
  instance_type = "t3.small"
  subnet_id     = aws_subnet.private_web_a.id
  key_name      = var.key_pair_name

  # Both security groups: AD client + RDP access
  vpc_security_group_ids = [
    aws_security_group.ad_client.id,
    aws_security_group.ad_automation.id
  ]

  iam_instance_profile = aws_iam_instance_profile.ad_automation.name

 
  user_data = base64encode(templatefile("${path.module}/scripts/ad_automation_userdata.ps1", {
    directory_id   = aws_directory_service_directory.main.id
    directory_name = aws_directory_service_directory.main.name
    dns_ip_1       = tolist(aws_directory_service_directory.main.dns_ip_addresses)[0]
    dns_ip_2       = tolist(aws_directory_service_directory.main.dns_ip_addresses)[1]
    secret_arn     = aws_secretsmanager_secret.ad_admin.arn
    sqs_queue_url  = aws_sqs_queue.ad_user_provisioning.url
    aws_region     = "eu-central-1"
  }))

  # Wait for AD to be created
  depends_on = [aws_directory_service_directory.main]

  tags = {
    Name = "${var.project_name}-ad-automation-server"
  }
}

# ==================== OUTPUTS ====================
output "ad_automation_instance_id" {
  value       = aws_instance.ad_automation.id
  description = "Windows automation server instance ID"
}

output "ad_automation_private_ip" {
  value       = aws_instance.ad_automation.private_ip
  description = "Windows automation server private IP"
}

output "sns_topic_arn" {
  value       = aws_sns_topic.ad_user_provisioning.arn
  description = "SNS topic ARN for AD user provisioning"
}

output "sqs_queue_url" {
  value       = aws_sqs_queue.ad_user_provisioning.url
  description = "SQS queue URL for AD user provisioning"
}

output "windows_automation_setup" {
  value = <<-EOT
  
  🪟 Windows Automation Server Setup:
  ====================================
  
  Instance ID: ${aws_instance.ad_automation.id}
  Private IP: ${aws_instance.ad_automation.private_ip}
  
  ⚠️  IMPORTANT - Manual Steps Required:
  
  1. Wait 20-30 minutes for AD to be "Active"
  2. Connect via RDP through VPN:
     - Server: ${aws_instance.ad_automation.private_ip}
     - Username: Administrator
     - Get password: AWS Console → EC2 → Get Windows Password
  
  3. Server will auto-join domain (check user-data logs)
  
  4. Create service account:
     PowerShell as Admin:
```
     New-ADUser -Name "svc-automation" -SamAccountName "svc-automation" `
       -UserPrincipalName "svc-automation@${aws_directory_service_directory.main.name}" `
       -AccountPassword (Read-Host -AsSecureString "Enter Password") `
       -Enabled $true -PasswordNeverExpires $true
```
  
  5. Delegate permissions (AD Users & Computers):
     - Right-click domain → Delegate Control
     - Add svc-automation
     - Grant: Create/delete users, reset passwords
  
  6. Store service account in Secrets Manager:
```
     aws secretsmanager create-secret --name ${var.project_name}-svc-automation `
       --secret-string '{"username":"svc-automation","password":"YourPassword"}'
```
  
  EOT
}