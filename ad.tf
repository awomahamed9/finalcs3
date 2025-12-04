# ==================== AWS MANAGED MICROSOFT AD ====================

# Directory Service for centralized user management
resource "aws_directory_service_directory" "main" {
  name     = "innovatech.local"
  password = var.ad_admin_password
  edition  = "Standard"  # Standard is enough for <500 users
  type     = "MicrosoftAD"

  vpc_settings {
    vpc_id     = aws_vpc.main.id
    subnet_ids = [aws_subnet.private_web_a.id, aws_subnet.private_web_b.id]
  }

  tags = {
    Name = "${var.project_name}-managed-ad"
  }
}

# ==================== OUTPUTS ====================
output "ad_directory_id" {
  value = aws_directory_service_directory.main.id
}

output "ad_dns_ips" {
  value = aws_directory_service_directory.main.dns_ip_addresses
}

output "ad_domain_name" {
  value = aws_directory_service_directory.main.name
}

output "ad_admin_credentials" {
  value = <<-EOT
  
  AWS Managed AD Setup Complete!
  ==============================
  
  Domain Name: ${aws_directory_service_directory.main.name}
  Directory ID: ${aws_directory_service_directory.main.id}
  DNS IPs: ${join(", ", aws_directory_service_directory.main.dns_ip_addresses)}
  
  Admin Credentials:
  Username: Admin
  Password: ${var.ad_admin_password}
  
  ⚠️  IMPORTANT: Wait 20-30 minutes for AD to be fully deployed!
  
  Check status: AWS Console → Directory Service
  
  EOT
  sensitive = true
}

# ==================== SECURITY GROUP FOR AD ====================
resource "aws_security_group" "ad" {
  name        = "${var.project_name}-ad-sg"
  description = "Security group for AWS Managed AD"
  vpc_id      = aws_vpc.main.id

  # Allow all traffic from VPC for AD communication
  ingress {
    description = "All traffic from VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ad-sg"
  }
}