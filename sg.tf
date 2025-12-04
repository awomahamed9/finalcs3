# ==================== SECURITY GROUPS ====================

# ==================== ALB SECURITY GROUP ====================
resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb-sg"
  description = "Security group for Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  # Allow HTTP from anywhere
  ingress {
    description = "HTTP from Internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Allow HTTPS from anywhere (optional for future)
  ingress {
    description = "HTTPS from Internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
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
    Name = "${var.project_name}-alb-sg"
  }
}

# ==================== HR PORTAL SECURITY GROUP ====================
resource "aws_security_group" "hr_portal" {
  name        = "${var.project_name}-hr-portal-sg"
  description = "Security group for HR Portal EC2"
  vpc_id      = aws_vpc.main.id

  # Allow traffic from ALB only
  ingress {
    description     = "HTTP from ALB"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # Allow SSH from VPN (for admin access)
  ingress {
    description     = "SSH from VPN"
    from_port       = 22
    to_port         = 22
    protocol        = "tcp"
    security_groups = [aws_security_group.openvpn.id]
  }

  # Allow all outbound (for DynamoDB, Docker pulls, etc)
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-hr-portal-sg"
  }
}

# ==================== VIRTUAL DESKTOP SECURITY GROUP ====================
resource "aws_security_group" "virtual_desktop" {
  name        = "${var.project_name}-virtual-desktop-sg"
  description = "Security group for Virtual Desktop EC2 with RDP (VPN access only)"
  vpc_id      = aws_vpc.main.id

  # Allow RDP from VPN clients only (via VPN subnet)
  ingress {
    description = "RDP from VPN clients"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"] # Only from within VPC (VPN connected)
  }

  # Allow SSH from VPN (for admin access)
  ingress {
    description     = "SSH from VPN"
    from_port       = 22
    to_port         = 22
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
    Name = "${var.project_name}-virtual-desktop-sg"
  }
}

# ==================== OPENVPN SECURITY GROUP ====================
resource "aws_security_group" "openvpn" {
  name        = "${var.project_name}-openvpn-sg"
  description = "Security group for OpenVPN Server"
  vpc_id      = aws_vpc.main.id

  # Allow OpenVPN from anywhere
  ingress {
    description = "OpenVPN from Internet"
    from_port   = 1194
    to_port     = 1194
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Allow SSH for initial setup
  ingress {
    description = "SSH for setup"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # Restrict this to your IP
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
    Name = "${var.project_name}-openvpn-sg"
  }
}

# ==================== GRAFANA SECURITY GROUP ====================
resource "aws_security_group" "grafana" {
  name        = "${var.project_name}-grafana-sg"
  description = "Security group for Grafana Monitoring"
  vpc_id      = aws_vpc.main.id

  # Allow Grafana web UI from VPN only
  ingress {
    description     = "Grafana from VPN"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.openvpn.id]
  }

  # Allow SSH from VPN
  ingress {
    description     = "SSH from VPN"
    from_port       = 22
    to_port         = 22
    protocol        = "tcp"
    security_groups = [aws_security_group.openvpn.id]
  }

  # Allow all outbound (for CloudWatch API)
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-grafana-sg"
  }
}

# ==================== OUTPUTS ====================
output "alb_sg_id" {
  value = aws_security_group.alb.id
}

output "hr_portal_sg_id" {
  value = aws_security_group.hr_portal.id
}

output "virtual_desktop_sg_id" {
  value = aws_security_group.virtual_desktop.id
}

output "openvpn_sg_id" {
  value = aws_security_group.openvpn.id
}

output "grafana_sg_id" {
  value = aws_security_group.grafana.id
}