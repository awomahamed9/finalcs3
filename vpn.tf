# ==================== VARIABLES ====================




# ==================== OPENVPN SECURITY GROUP ====================


# ==================== OPENVPN SERVER ====================
resource "aws_instance" "openvpn" {
  ami                         = data.aws_ami.amazon_linux_2.id
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.public_a.id
  key_name                    = var.key_pair_name
  vpc_security_group_ids      = [aws_security_group.openvpn.id]
  associate_public_ip_address = true
  source_dest_check           = false

  user_data = <<-EOF
              #!/bin/bash
              set -e
              
              # Wait for system to be ready
              sleep 30
              
              # Download and run OpenVPN install script
              cd /root
              curl -O https://raw.githubusercontent.com/angristan/openvpn-install/master/openvpn-install.sh
              chmod +x openvpn-install.sh
              
              # Set environment variables for non-interactive install
              export AUTO_INSTALL=y
              export APPROVE_INSTALL=y
              export APPROVE_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
              export IPV6_SUPPORT=n
              export PORT_CHOICE=1
              export PROTOCOL_CHOICE=1
              export DNS=1
              export COMPRESSION_ENABLED=n
              export CUSTOMIZE_ENC=n
              export CLIENT=employee
              export PASS=1
              
              # Run installer
              bash openvpn-install.sh
              
              # Wait for config to be created
              sleep 10
              
              # Copy client config to ec2-user home
              if [ -f /root/employee.ovpn ]; then
                cp /root/employee.ovpn /home/ec2-user/
                chown ec2-user:ec2-user /home/ec2-user/employee.ovpn
              fi
              
              # Create helper script for creating new VPN users
              cat > /home/ec2-user/create-vpn-user.sh << 'SCRIPT'
              #!/bin/bash
              if [ -z "$1" ]; then
                echo "Usage: ./create-vpn-user.sh <username>"
                exit 1
              fi
              
              export MENU_OPTION=1
              export CLIENT=$1
              export PASS=1
              
              sudo bash /root/openvpn-install.sh
              
              if [ -f /root/$1.ovpn ]; then
                sudo cp /root/$1.ovpn /home/ec2-user/
                sudo chown ec2-user:ec2-user /home/ec2-user/$1.ovpn
                echo "✅ VPN config created: /home/ec2-user/$1.ovpn"
                echo "Download with: scp -i ~/.ssh/case3-keypair.pem ec2-user@$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):$1.ovpn ./"
              else
                echo "❌ Failed to create VPN config"
              fi
              SCRIPT
              
              chmod +x /home/ec2-user/create-vpn-user.sh
              chown ec2-user:ec2-user /home/ec2-user/create-vpn-user.sh
              
              # Create README
              cat > /home/ec2-user/README.txt << 'README'
              OpenVPN Server Setup Complete!
              
              Default VPN config: employee.ovpn
              
              To create additional VPN users:
              ./create-vpn-user.sh <username>
              
              To download config:
              scp -i ~/.ssh/case3-keypair.pem ec2-user@<server-ip>:employee.ovpn ./
              README
              
              echo "OpenVPN setup completed successfully" > /var/log/openvpn-setup.log
              EOF

  tags = {
    Name = "${var.project_name}-openvpn-server"
  }
}

# Elastic IP for OpenVPN
resource "aws_eip" "openvpn" {
  instance = aws_instance.openvpn.id
  domain   = "vpc"

  tags = {
    Name = "${var.project_name}-openvpn-eip"
  }
}

# ==================== OUTPUTS ====================
output "openvpn_public_ip" {
  value       = aws_eip.openvpn.public_ip
  description = "OpenVPN server public IP"
}

output "openvpn_setup_complete" {
  value = <<-EOT
  
  ✅ OpenVPN Server Setup Instructions:
  =====================================
  
  Server IP: ${aws_eip.openvpn.public_ip}
  
  IMPORTANT: Wait 5 minutes for setup to complete, then:
  
  1. Update VPN configs with correct Elastic IP:
     ssh -i ~/.ssh/${var.key_pair_name}.pem ec2-user@${aws_eip.openvpn.public_ip}
     ./create-vpn-user.sh employee
     exit
  
  2. Download VPN config:
     scp -i ~/.ssh/${var.key_pair_name}.pem ec2-user@${aws_eip.openvpn.public_ip}:employee.ovpn ./
  
  3. Import employee.ovpn into OpenVPN Connect client
  
  4. Connect to VPN
  
  To create additional VPN users later:
     ssh -i ~/.ssh/${var.key_pair_name}.pem ec2-user@${aws_eip.openvpn.public_ip}
     ./create-vpn-user.sh <username>
  
  EOT
}