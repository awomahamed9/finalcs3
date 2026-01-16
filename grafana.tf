# ==================== IAM ROLE FOR GRAFANA ====================
# Allows Grafana to read CloudWatch metrics without access keys
resource "aws_iam_role" "grafana" {
  name = "${var.project_name}-grafana-role"

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
    Name = "${var.project_name}-grafana-role"
  }
}

# Attach CloudWatch Read Only access
resource "aws_iam_role_policy_attachment" "grafana_cloudwatch" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
}

resource "aws_iam_instance_profile" "grafana" {
  name = "${var.project_name}-grafana-profile"
  role = aws_iam_role.grafana.name
}

# ==================== GRAFANA EC2 INSTANCE ====================
resource "aws_instance" "grafana" {
  ami                    = data.aws_ami.amazon_linux_2.id # Reuses AMI defined in vpc.tf
  instance_type          = "t3.small"
  subnet_id              = aws_subnet.monitoring.id       # Defined in vpc.tf
  key_name               = var.key_pair_name
  vpc_security_group_ids = [aws_security_group.grafana.id] # Defined in sg.tf
  iam_instance_profile   = aws_iam_instance_profile.grafana.name

  user_data = <<-EOF
              #!/bin/bash
              # 1. Update and Install Grafana
              yum update -y
              cat > /etc/yum.repos.d/grafana.repo <<REPO
              [grafana]
              name=grafana
              baseurl=https://packages.grafana.com/oss/rpm
              repo_gpgcheck=1
              enabled=1
              gpgcheck=1
              gpgkey=https://packages.grafana.com/gpg.key
              sslverify=1
              sslcacert=/etc/pki/tls/certs/ca-bundle.crt
              REPO
              
              yum install -y grafana
              
              # 2. Configure CloudWatch Datasource Automatically
              # This tells Grafana to use the attached IAM Role
              cat <<EOT > /etc/grafana/provisioning/datasources/cloudwatch.yaml
              apiVersion: 1
              datasources:
                - name: CloudWatch
                  type: cloudwatch
                  isDefault: true
                  jsonData:
                    authType: default_iam_role
                    defaultRegion: eu-central-1
              EOT

              # 3. Start Grafana Server
              systemctl daemon-reload
              systemctl enable grafana-server
              systemctl start grafana-server
              EOF

  tags = {
    Name = "${var.project_name}-grafana"
  }
}

# ==================== OUTPUTS ====================
output "grafana_private_ip" {
  value       = aws_instance.grafana.private_ip
  description = "Grafana Private IP (Access via VPN)"
}

output "grafana_url" {
  value       = "http://${aws_instance.grafana.private_ip}:3000"
  description = "Grafana URL (Requires VPN Connection)"
}