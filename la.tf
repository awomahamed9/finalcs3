# ==================== VARIABLES ====================
variable "ses_sender_email" {
  description = "Email address to send employee credentials from (must be verified in SES)"
  type        = string
  default     = "549500@student.fontys.nl"
}

# ==================== SES EMAIL IDENTITY ====================
resource "aws_ses_email_identity" "sender" {
  email = var.ses_sender_email
}

# ==================== IAM ROLE FOR LAMBDA ====================
resource "aws_iam_role" "lambda_provisioning" {
  name = "${var.project_name}-lambda-provisioning-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-lambda-provisioning-role"
  }
}

# Lambda basic execution policy
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_provisioning.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda VPC execution policy
resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda_provisioning.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Custom policy for Lambda permissions
resource "aws_iam_role_policy" "lambda_permissions" {
  name = "${var.project_name}-lambda-permissions"
  role = aws_iam_role.lambda_provisioning.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:DescribeStream",
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
          "dynamodb:ListStreams"
        ]
        Resource = [
          aws_dynamodb_table.employees.arn,
          "${aws_dynamodb_table.employees.arn}/stream/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:DescribeInstances",
          "ec2:CreateTags",
          "ec2:DescribeImages"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = aws_iam_role.virtual_desktop.arn
      },
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
        ]
        Resource = "*"
      },

      # Add to la.tf in aws_iam_role_policy
      {
        Effect = "Allow"
        Action = [
          "ds:DescribeDirectories",
          "ssm:SendCommand", # If using SSM for domain join
          "ssm:GetCommandInvocation"
        ]
        Resource = "*"
      },

      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.ad_user_provisioning.arn
      }




    ]
  })
}

# ==================== LAMBDA SECURITY GROUP ====================
resource "aws_security_group" "lambda" {
  name        = "${var.project_name}-lambda-sg"
  description = "Security group for Lambda function"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-lambda-sg"
  }
}

# ==================== LAMBDA FUNCTION ====================
# Get Ubuntu AMI for virtual desktops
data "aws_ami" "ubuntu_desktop" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/user_provisioning.py"
  output_path = "${path.module}/lambda/user_provisioning.zip"
}

resource "aws_lambda_function" "user_provisioning" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_name}-user-provisioning"
  role             = aws_iam_role.lambda_provisioning.arn
  handler          = "user_provisioning.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 300 # 5 minutes
  memory_size      = 256

  vpc_config {
    subnet_ids         = [aws_subnet.private_web_a.id, aws_subnet.private_web_b.id]
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DYNAMODB_TABLE       = aws_dynamodb_table.employees.name
      SES_SENDER_EMAIL     = var.ses_sender_email
      OPENVPN_SERVER_IP    = aws_eip.openvpn.public_ip
      SUBNET_ID            = aws_subnet.private_web_a.id
      SECURITY_GROUP_ID    = aws_security_group.virtual_desktop.id
      AD_CLIENT_SG_ID      = aws_security_group.ad_client.id
      SNS_TOPIC_ARN        = aws_sns_topic.ad_user_provisioning.arn
      AMI_ID               = data.aws_ami.ubuntu_desktop.id
      KEY_NAME             = var.key_pair_name
      IAM_INSTANCE_PROFILE = "cs3-nca-virtual-desktop-profile"
    }
  }

  tags = {
    Name = "${var.project_name}-user-provisioning"
  }
}

# ==================== DYNAMODB STREAM TRIGGER ====================
resource "aws_lambda_event_source_mapping" "dynamodb_stream" {
  event_source_arn  = aws_dynamodb_table.employees.stream_arn
  function_name     = aws_lambda_function.user_provisioning.arn
  starting_position = "LATEST"

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT"]
        dynamodb = {
          NewImage = {
            processed = {
              BOOL = [false]
            }
          }
        }
      })
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda_permissions,
    aws_iam_role_policy_attachment.lambda_basic
  ]
}

# ==================== CLOUDWATCH LOG GROUP ====================
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.user_provisioning.function_name}"
  retention_in_days = 7

  tags = {
    Name = "${var.project_name}-lambda-logs"
  }
}

# ==================== OUTPUTS ====================
output "lambda_function_name" {
  value = aws_lambda_function.user_provisioning.function_name
}

output "lambda_function_arn" {
  value = aws_lambda_function.user_provisioning.arn
}

output "ses_verification_instructions" {
  value = <<-EOT
  
  ⚠️  IMPORTANT - SES Email Verification Required!
  
  1. Check your email: ${var.ses_sender_email}
  2. Click the verification link from AWS
  3. Or verify in AWS Console: SES → Verified identities
  
  Lambda will fail to send emails until this is verified!
  
  EOT
}