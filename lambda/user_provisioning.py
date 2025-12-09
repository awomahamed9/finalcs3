import json
import boto3
import os
import random
import string
from datetime import datetime

# AWS clients
dynamodb = boto3.client('dynamodb')
ec2 = boto3.client('ec2')
sns = boto3.client('sns')
ses = boto3.client('ses')

# Environment variables
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']
SES_SENDER_EMAIL = os.environ['SES_SENDER_EMAIL']
OPENVPN_SERVER_IP = os.environ['OPENVPN_SERVER_IP']
SUBNET_ID = os.environ['SUBNET_ID']
SECURITY_GROUP_ID = os.environ['SECURITY_GROUP_ID']
AD_CLIENT_SG_ID = os.environ['AD_CLIENT_SG_ID']
AMI_ID = os.environ['AMI_ID']
KEY_NAME = os.environ['KEY_NAME']
IAM_INSTANCE_PROFILE = os.environ.get('IAM_INSTANCE_PROFILE', 'cs3-nca-virtual-desktop-profile')
AD_DOMAIN = "innovatech.local"
AD_DNS_1 = "10.0.11.44"
AD_DNS_2 = "10.0.12.42"

def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    for record in event['Records']:
        if record['eventName'] == 'INSERT':
            new_image = record['dynamodb']['NewImage']
            
            employee_id = new_image['id']['S']
            name = new_image['name']['S']
            email = new_image['email']['S']
            username = new_image['username']['S']
            role = new_image.get('role', {}).get('S', 'Analyst')
            department = new_image['department']['S']
            processed = new_image.get('processed', {}).get('BOOL', False)
            
            if processed:
                print(f"Employee {employee_id} already processed, skipping")
                continue
            
            print(f"Processing new employee: {name} ({username})")
            
            try:
                password = generate_password()
                print(f"Generated password for {username}")
                
                # Step 1: Publish to SNS for AD user creation
                message = {
                    'employee_id': employee_id,
                    'name': name,
                    'username': username,
                    'password': password,
                    'email': email,
                    'role': role,
                    'department': department
                }
                
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Message=json.dumps(message),
                    Subject=f'Create AD User: {username}'
                )
                
                print(f"✅ Published message to SNS for {username}")
                
                # Step 2: Launch domain-joined virtual desktop
                instance_id, private_ip = launch_virtual_desktop(
                    employee_id, name, username, department, role
                )
                
                if not instance_id:
                    raise Exception(f"Failed to launch EC2 instance for {username}")
                
                print(f"✅ Launched EC2: {instance_id} ({private_ip})")
                
                # Step 3: Send credentials email
                send_credentials_email(name, email, username, password, private_ip, role)
                
                # Step 4: Update employee status
                update_employee_status(
                    employee_id,
                    processed=True,
                    instance_id=instance_id,
                    private_ip=private_ip,
                    assigned_role=role
                )
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'message': f'Successfully provisioned desktop for {username}',
                        'employee_id': employee_id,
                        'instance_id': instance_id
                    })
                }
                
            except Exception as e:
                print(f"Error: {str(e)}")
                import traceback
                traceback.print_exc()
                return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}

def generate_password(length=12):
    """Generate secure random password"""
    characters = string.ascii_letters + string.digits + "!@#$%"
    password = ''.join(random.choice(characters) for i in range(length))
    if not any(c.isupper() for c in password):
        password = password[:-1] + random.choice(string.ascii_uppercase)
    if not any(c.isdigit() for c in password):
        password = password[:-1] + random.choice(string.digits)
    return password

def launch_virtual_desktop(employee_id, name, username, department, role):
    """Launch domain-joined EC2 virtual desktop"""
    try:
        # User data script for domain join
       user_data = f"""#!/bin/bash
set -e

# Log everything
exec > >(tee /var/log/user-data.log)
exec 2>&1

echo "=== Starting Virtual Desktop Setup for {username} ==="

# Update system
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

# Install desktop environment
DEBIAN_FRONTEND=noninteractive apt-get install -y xfce4 xfce4-goodies xrdp

# Install realmd for domain join
DEBIAN_FRONTEND=noninteractive apt-get install -y realmd sssd sssd-tools adcli krb5-user packagekit samba-common-bin

# Configure DNS to AD (don't use chattr - not supported on EC2)
cat > /etc/resolv.conf << EOF
nameserver {AD_DNS_1}
nameserver {AD_DNS_2}
search {AD_DOMAIN}
EOF

# Prevent NetworkManager from overwriting resolv.conf
cat > /etc/NetworkManager/conf.d/dns.conf << EOF
[main]
dns=none
EOF
systemctl restart NetworkManager || true

# Configure xrdp
systemctl enable xrdp
systemctl start xrdp

# Allow RDP through firewall
ufw allow 3389/tcp || true
ufw --force enable || true

# Wait for AD to be reachable (fixed bash syntax)
echo "Waiting for AD..."
for i in $(seq 1 30); do
    if ping -c 1 {AD_DNS_1} &> /dev/null; then
        echo "AD is reachable!"
        break
    fi
    echo "Attempt $i/30..."
    sleep 10
done

# Discover and join domain
echo "Discovering domain..."
realm discover {AD_DOMAIN}

echo "Joining domain..."
echo "InnovatechAD2024!" | realm join --user=Admin {AD_DOMAIN}

# Verify domain join
realm list

# Configure SSSD for domain authentication
cat > /etc/sssd/sssd.conf << EOF
[sssd]
domains = {AD_DOMAIN}
config_file_version = 2
services = nss, pam

[domain/{AD_DOMAIN}]
default_shell = /bin/bash
krb5_store_password_if_offline = True
cache_credentials = True
krb5_realm = {AD_DOMAIN.upper()}
id_provider = ad
fallback_homedir = /home/%u
ad_domain = {AD_DOMAIN}
use_fully_qualified_names = False
ldap_id_mapping = True
access_provider = ad
EOF

chmod 600 /etc/sssd/sssd.conf
systemctl enable sssd
systemctl restart sssd

# Configure PAM for home directory creation
pam-auth-update --enable mkhomedir

# Create welcome file
cat > /etc/skel/WELCOME.txt << 'WELCOME'
========================================
INNOVATECH VIRTUAL DESKTOP
========================================

Employee: {name}
Username: {username}
Role: {role}
Department: {department}

This desktop is domain-joined to {AD_DOMAIN}

Log in with your domain credentials:
Username: {username}
Password: (sent to your email)

For support: it@innovatech.com
========================================
WELCOME

echo "=== ✅ Setup completed successfully for {username} ==="
"""

        # Launch instance
        response = ec2.run_instances(
            ImageId=AMI_ID,
            InstanceType='t3.medium',
            KeyName=KEY_NAME,
            IamInstanceProfile={'Name': IAM_INSTANCE_PROFILE},
            MinCount=1,
            MaxCount=1,
            NetworkInterfaces=[{
                'SubnetId': SUBNET_ID,
                'DeviceIndex': 0,
                'AssociatePublicIpAddress': False,
                'Groups': [SECURITY_GROUP_ID, AD_CLIENT_SG_ID]
            }],
            UserData=user_data,
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [
                    {'Key': 'Name', 'Value': f'virtual-desktop-{username}'},
                    {'Key': 'Employee', 'Value': name},
                    {'Key': 'EmployeeId', 'Value': employee_id},
                    {'Key': 'Department', 'Value': department},
                    {'Key': 'Role', 'Value': role},
                    {'Key': 'DomainJoined', 'Value': 'True'},
                    {'Key': 'Project', 'Value': 'cs3-nca'}
                ]
            }],
            BlockDeviceMappings=[{
                'DeviceName': '/dev/sda1',
                'Ebs': {
                    'VolumeSize': 30,
                    'VolumeType': 'gp3',
                    'DeleteOnTermination': True,
                    'Encrypted': True
                }
            }]
        )
        
        instance_id = response['Instances'][0]['InstanceId']
        private_ip = response['Instances'][0]['PrivateIpAddress']
        
        print(f"Launched domain-joined instance: {instance_id} at {private_ip}")
        return instance_id, private_ip
        
    except Exception as e:
        print(f"Error launching instance: {str(e)}")
        return None, None

def send_credentials_email(name, email, username, password, private_ip, role):
    """Send welcome email with AD credentials"""
    try:
        first_name = name.split()[0]
        
        subject = f"Welcome to Innovatech - Your Domain Account & Virtual Desktop"
        
        html_body = f"""<html>
<head>
<style>
body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
.container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
.header {{ background: #2563eb; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
.content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 8px 8px; }}
.credentials {{ background: white; padding: 20px; border-left: 4px solid #2563eb; margin: 20px 0; border-radius: 4px; }}
.credential-item {{ margin: 10px 0; }}
.label {{ font-weight: bold; color: #374151; }}
.value {{ font-family: monospace; background: #f3f4f6; padding: 5px 10px; border-radius: 4px; }}
.warning {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0; border-radius: 4px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Welcome to Innovatech!</h1>
    <p>Your domain account and virtual desktop are ready</p>
  </div>
  
  <div class="content">
    <p>Hi {first_name},</p>
    
    <p>Your Active Directory account and domain-joined virtual desktop have been provisioned.</p>
    
    <div class="credentials">
      <h3>Your Domain Credentials</h3>
      <div class="credential-item">
        <span class="label">Domain:</span>
        <span class="value">{AD_DOMAIN}</span>
      </div>
      <div class="credential-item">
        <span class="label">Username:</span>
        <span class="value">{username}</span>
      </div>
      <div class="credential-item">
        <span class="label">Password:</span>
        <span class="value">{password}</span>
      </div>
      <div class="credential-item">
        <span class="label">Desktop IP:</span>
        <span class="value">{private_ip}:3389</span>
      </div>
      <div class="credential-item">
        <span class="label">VPN Server:</span>
        <span class="value">{OPENVPN_SERVER_IP}</span>
      </div>
    </div>
    
    <div class="warning">
      <strong>⚠️ Important:</strong> Your desktop is domain-joined. It may take 10-15 minutes to fully provision and join the domain.
    </div>
    
    <h3>How to Connect:</h3>
    <ol>
      <li><strong>Connect to VPN first</strong> (contact IT for VPN config)</li>
      <li><strong>Open Remote Desktop client</strong></li>
      <li><strong>Server:</strong> {private_ip}:3389</li>
      <li><strong>Login with:</strong>
        <ul>
          <li>Username: <code>{username}</code> (or <code>{username}@{AD_DOMAIN}</code>)</li>
          <li>Password: <code>{password}</code></li>
        </ul>
      </li>
    </ol>
    
    <p>Questions? Contact IT: <a href="mailto:it@innovatech.com">it@innovatech.com</a></p>
    
    <p>Welcome aboard!</p>
    <p><strong>The Innovatech IT Team</strong></p>
  </div>
</div>
</body>
</html>"""
        
        text_body = f"""Welcome to Innovatech!

Hi {first_name},

Your Active Directory account and domain-joined virtual desktop are ready.

DOMAIN CREDENTIALS:
Domain: {AD_DOMAIN}
Username: {username}
Password: {password}
Desktop IP: {private_ip}:3389
VPN Server: {OPENVPN_SERVER_IP}

IMPORTANT: Desktop may take 10-15 minutes to fully provision.

HOW TO CONNECT:
1. Connect to VPN first
2. Open Remote Desktop client
3. Server: {private_ip}:3389
4. Login: {username} / {password}

Questions? Contact IT: it@innovatech.com

Welcome aboard!
The Innovatech IT Team
"""
        
        ses.send_email(
            Source=SES_SENDER_EMAIL,
            Destination={'ToAddresses': [email]},
            Message={
                'Subject': {'Data': subject},
                'Body': {
                    'Text': {'Data': text_body},
                    'Html': {'Data': html_body}
                }
            }
        )
        
        print(f"✅ Email sent to {email}")
        return True
        
    except Exception as e:
        print(f"Email error: {str(e)}")
        return False

def update_employee_status(employee_id, processed=True, instance_id=None, private_ip=None, assigned_role=None):
    """Update employee record"""
    try:
        update_expr = 'SET #proc = :proc, processed_at = :time'
        expr_names = {'#proc': 'processed'}
        expr_values = {
            ':proc': {'BOOL': processed},
            ':time': {'S': datetime.utcnow().isoformat()}
        }
        
        if instance_id:
            update_expr += ', instance_id = :inst'
            expr_values[':inst'] = {'S': instance_id}
        
        if private_ip:
            update_expr += ', private_ip = :ip'
            expr_values[':ip'] = {'S': private_ip}
            
        if assigned_role:
            update_expr += ', rbac_role = :role'
            expr_values[':role'] = {'S': assigned_role}
        
        dynamodb.update_item(
            TableName=DYNAMODB_TABLE,
            Key={'id': {'S': employee_id}},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values
        )
        
        print(f"Updated employee {employee_id}")
        return True
        
    except Exception as e:
        print(f"Update error: {str(e)}")
        return False