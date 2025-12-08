# # ==================== VARIABLES ====================
# variable "hr_admin_username" {
#   description = "Admin username for HR Portal"
#   type        = string
#   default     = "admin"
# }

# variable "hr_admin_password" {
#   description = "Admin password for HR Portal"
#   type        = string
#   default     = "Student123"
#   sensitive   = true
# }

# # ==================== IAM ROLE FOR HR PORTAL ====================
# resource "aws_iam_role" "hr_portal" {
#   name = "${var.project_name}-hr-portal-role"

#   assume_role_policy = jsonencode({
#     Version = "2012-10-17"
#     Statement = [
#       {
#         Action = "sts:AssumeRole"
#         Effect = "Allow"
#         Principal = {
#           Service = "ec2.amazonaws.com"
#         }
#       }
#     ]
#   })

#   tags = {
#     Name = "${var.project_name}-hr-portal-role"
#   }
# }

# # Policy for DynamoDB access
# resource "aws_iam_role_policy" "hr_portal_dynamodb" {
#   name = "${var.project_name}-hr-portal-dynamodb-policy"
#   role = aws_iam_role.hr_portal.id

#   policy = jsonencode({
#     Version = "2012-10-17"
#     Statement = [
#       {
#         Effect = "Allow"
#         Action = [
#           "dynamodb:PutItem",
#           "dynamodb:GetItem",
#           "dynamodb:Scan",
#           "dynamodb:Query",
#           "dynamodb:UpdateItem"
#         ]
#         Resource = aws_dynamodb_table.employees.arn
#       }
#     ]
#   })
# }

# # Attach SSM policy for remote management
# resource "aws_iam_role_policy_attachment" "hr_portal_ssm" {
#   role       = aws_iam_role.hr_portal.name
#   policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
# }

# # Attach ECR read policy for Docker pulls
# resource "aws_iam_role_policy_attachment" "hr_portal_ecr" {
#   role       = aws_iam_role.hr_portal.name
#   policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
# }

# # Create instance profile
# resource "aws_iam_instance_profile" "hr_portal" {
#   name = "${var.project_name}-hr-portal-profile"
#   role = aws_iam_role.hr_portal.name
# }

# # ==================== HR PORTAL EC2 ====================
# resource "aws_instance" "hr_portal" {
#   ami                    = data.aws_ami.amazon_linux_2.id
#   instance_type          = "t3.small"
#   subnet_id              = aws_subnet.private_web_a.id
#   key_name               = var.key_pair_name
#   vpc_security_group_ids = [aws_security_group.hr_portal.id]
#   iam_instance_profile   = aws_iam_instance_profile.hr_portal.name

#   user_data = base64encode(templatefile("${path.module}/scripts/hr_portal_user_data.sh", {
#     dynamodb_table_name = aws_dynamodb_table.employees.name
#     aws_region          = "eu-central-1"
#     admin_username      = var.hr_admin_username
#     admin_password      = var.hr_admin_password
#   }))

#   root_block_device {
#     volume_size           = 20
#     volume_type           = "gp3"
#     delete_on_termination = true
#     encrypted             = true
#   }

#   tags = {
#     Name = "${var.project_name}-hr-portal"
#   }
# }

# # ==================== OUTPUTS ====================
# output "hr_portal_instance_id" {
#   value = aws_instance.hr_portal.id
# }

# output "hr_portal_private_ip" {
#   value = aws_instance.hr_portal.private_ip
# }


# output "hr_portal_credentials" {
#   value     = <<-EOT

#   HR Portal Login Credentials:
#   ----------------------------
#   Username: ${var.hr_admin_username}
#   Password: ${var.hr_admin_password}

#   URL: http://${aws_instance.hr_portal.private_ip}:3000

#   ⚠️  Change these credentials in your Terraform variables!

#   EOT
#   sensitive = true
# }