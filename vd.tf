# ==================== IAM ROLE FOR VIRTUAL DESKTOPS ====================
# This role will be attached to all employee virtual desktop instances
resource "aws_iam_role" "virtual_desktop" {
  name = "${var.project_name}-virtual-desktop-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-virtual-desktop-role"
  }
}

# Attach SSM policy
resource "aws_iam_role_policy_attachment" "virtual_desktop_ssm" {
  role       = aws_iam_role.virtual_desktop.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Create instance profile
resource "aws_iam_instance_profile" "virtual_desktop" {
  name = "${var.project_name}-virtual-desktop-profile"
  role = aws_iam_role.virtual_desktop.name
}

resource "aws_iam_role_policy" "virtual_desktop_domain_join" {
  name = "${var.project_name}-virtual-desktop-domain-join"
  role = aws_iam_role.virtual_desktop.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ds:DescribeDirectories",
          "secretsmanager:GetSecretValue" 
        ]
        Resource = "*"
      }
    ]
  })
}

# ==================== OUTPUTS ====================
output "virtual_desktop_iam_role_arn" {
  value       = aws_iam_role.virtual_desktop.arn
  description = "IAM role ARN used by virtual desktop instances"
}

output "virtual_desktop_security_group_id" {
  value       = aws_security_group.virtual_desktop.id
  description = "Security group ID for virtual desktop instances"
}