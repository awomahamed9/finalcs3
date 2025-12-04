#!/bin/bash
set -e

# Variables from Terraform
VPC_CIDR="${vpc_cidr}"
VPN_CLIENT_CIDR="${vpn_client_cidr}"
DNS_SERVER="${dns_server}"

# Update system
yum update -y

# Install OpenVPN and Easy-RSA
yum install -y openvpn easy-rsa

# Set up Easy-RSA
make-cadir /root/openvpn-ca
cd /root/openvpn-ca

# Create vars file
cat > vars << 'EOF'
set_var EASYRSA_REQ_COUNTRY    "NL"
set_var EASYRSA_REQ_PROVINCE   "Zuid-Holland"
set_var EASYRSA_REQ_CITY       "Rotterdam"
set_var EASYRSA_REQ_ORG        "Innovatech"
set_var EASYRSA_REQ_EMAIL      "admin@innovatech.com"
set_var EASYRSA_REQ_OU         "IT"
set_var EASYRSA_ALGO           "ec"
set_var EASYRSA_DIGEST         "sha512"
EOF

# Initialize PKI
./easyrsa init-pki

# Build CA (non-interactive)
echo "innovatech-ca" | ./easyrsa build-ca nopass

# Generate server certificate
echo "yes" | ./easyrsa build-server-full server nopass

# Generate DH parameters
./easyrsa gen-dh

# Generate TLS auth key
openvpn --genkey secret pki/ta.key

# Copy certificates
cp pki/ca.crt /etc/openvpn/server/
cp pki/issued/server.crt /etc/openvpn/server/
cp pki/private/server.key /etc/openvpn/server/
cp pki/dh.pem /etc/openvpn/server/
cp pki/ta.key /etc/openvpn/server/

# Create OpenVPN server configuration
cat > /etc/openvpn/server/server.conf << SERVERCONF
port 1194
proto udp
dev tun

ca ca.crt
cert server.crt
key server.key
dh dh.pem
tls-auth ta.key 0

server $VPN_CLIENT_CIDR 255.255.255.0

# Push routes to VPC
push "route $VPC_CIDR"

# DNS
push "dhcp-option DNS $DNS_SERVER"

keepalive 10 120
cipher AES-256-GCM
auth SHA256
user nobody
group nobody
persist-key
persist-tun

status /var/log/openvpn-status.log
log-append /var/log/openvpn.log
verb 3
SERVERCONF

# Enable IP forwarding
echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf
sysctl -p

# Configure firewall
systemctl enable firewalld
systemctl start firewalld

# Allow OpenVPN through firewall
firewall-cmd --permanent --add-service=openvpn
firewall-cmd --permanent --zone=trusted --add-service=openvpn
firewall-cmd --permanent --zone=trusted --add-interface=tun0

# Add masquerading for VPN clients
firewall-cmd --permanent --add-masquerade
firewall-cmd --reload

# Enable and start OpenVPN
systemctl enable openvpn-server@server
systemctl start openvpn-server@server

# Create client config directory
mkdir -p /root/client-configs

# Get server public IP (will be Elastic IP)
SERVER_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

# Create client config template
cat > /root/client-configs/base.conf << BASECONF
client
dev tun
proto udp
remote $SERVER_IP 1194
resolv-retry infinite
nobind
user nobody
group nobody
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
auth SHA256
key-direction 1
verb 3
BASECONF

# Create script to generate client configs
cat > /root/client-configs/make_config.sh << 'MAKESCRIPT'
#!/bin/bash

CLIENT_NAME=$1

if [ -z "$CLIENT_NAME" ]; then
    echo "Usage: ./make_config.sh <client_name>"
    exit 1
fi

cd /root/openvpn-ca
echo "yes" | ./easyrsa build-client-full $CLIENT_NAME nopass

cd /root/client-configs

cat base.conf > $CLIENT_NAME.ovpn

echo "<ca>" >> $CLIENT_NAME.ovpn
cat /root/openvpn-ca/pki/ca.crt >> $CLIENT_NAME.ovpn
echo "</ca>" >> $CLIENT_NAME.ovpn

echo "<cert>" >> $CLIENT_NAME.ovpn
cat /root/openvpn-ca/pki/issued/$CLIENT_NAME.crt >> $CLIENT_NAME.ovpn
echo "</cert>" >> $CLIENT_NAME.ovpn

echo "<key>" >> $CLIENT_NAME.ovpn
cat /root/openvpn-ca/pki/private/$CLIENT_NAME.key >> $CLIENT_NAME.ovpn
echo "</key>" >> $CLIENT_NAME.ovpn

echo "<tls-auth>" >> $CLIENT_NAME.ovpn
cat /root/openvpn-ca/pki/ta.key >> $CLIENT_NAME.ovpn
echo "</tls-auth>" >> $CLIENT_NAME.ovpn

# Copy to ec2-user home for easy download
cp $CLIENT_NAME.ovpn /home/ec2-user/
chown ec2-user:ec2-user /home/ec2-user/$CLIENT_NAME.ovpn

echo "Client config created: /home/ec2-user/$CLIENT_NAME.ovpn"
MAKESCRIPT

chmod +x /root/client-configs/make_config.sh

# Create default client config
/root/client-configs/make_config.sh client

# Create symlink for easy access
ln -s /home/ec2-user/client.ovpn /home/ec2-user/

echo "OpenVPN setup completed" > /var/log/openvpn-setup.log