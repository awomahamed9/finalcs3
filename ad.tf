# ==================== AWS MANAGED ACTIVE DIRECTORY ====================

# Service account password stored in Secrets Manager
resource "aws_secretsmanager_secret" "ad_admin" {
  name        = "${var.project_name}-ad-admin-password"
  description = "Admin password for AWS Managed AD"

  tags = {
    Name = "${var.project_name}-ad-admin-password"
  }
}

resource "aws_secretsmanager_secret_version" "ad_admin" {
  secret_id = aws_secretsmanager_secret.ad_admin.id
  secret_string = jsonencode({
    username = "Admin"
    password = var.ad_admin_password
  })
}

# AWS Managed Microsoft AD
resource "aws_directory_service_directory" "main" {
  name     = "innovatech.local"
  password = var.ad_admin_password
  edition  = "Standard" # Standard is cheaper for testing
  type     = "MicrosoftAD"

  vpc_settings {
    vpc_id = aws_vpc.main.id
    subnet_ids = [
      aws_subnet.private_web_a.id,
      aws_subnet.private_web_b.id
    ]
  }

  tags = {
    Name = "${var.project_name}-managed-ad"
  }
}

# ==================== OUTPUTS ====================
output "ad_directory_id" {
  value       = aws_directory_service_directory.main.id
  description = "AWS Managed AD Directory ID"
}

output "ad_domain_name" {
  value       = aws_directory_service_directory.main.name
  description = "AD Domain Name"
}

output "ad_dns_ips" {
  value       = aws_directory_service_directory.main.dns_ip_addresses
  description = "AD Domain Controller DNS IPs"
}

output "ad_setup_instructions" {
  value = <<-EOT
  
  ✅ AWS Managed AD Created!
  ===========================
  
  Directory ID: ${aws_directory_service_directory.main.id}
  Domain: ${aws_directory_service_directory.main.name}
  DNS IPs: ${join(", ", aws_directory_service_directory.main.dns_ip_addresses)}
  
  Admin Username: Admin
  Admin Password: (stored in Secrets Manager: ${aws_secretsmanager_secret.ad_admin.name})
  
  ⚠️  WAIT 20-30 MINUTES for AD to fully provision before domain joining!
  
  Next Steps:
  1. Wait for AD to be "Active" status in AWS Console
  2. RDP to Windows automation server
  3. Create service account for automation
  
  EOT
}