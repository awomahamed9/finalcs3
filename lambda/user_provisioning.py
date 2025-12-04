import json
import boto3
import os
import time
import random
import string
from datetime import datetime

# AWS clients
dynamodb = boto3.client('dynamodb')
ec2 = boto3.client('ec2')
ses = boto3.client('ses')
ds = boto3.client('ds')  # Directory Service for AD

# Environment variables
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
SES_SENDER_EMAIL = os.environ['SES_SENDER_EMAIL']
OPENVPN_SERVER_IP = os.environ['OPENVPN_SERVER_IP']
SUBNET_ID = os.environ['SUBNET_ID']
SECURITY_GROUP_ID = os.environ['SECURITY_GROUP_ID']
AMI_ID = os.environ['AMI_ID']
KEY_NAME = os.environ['KEY_NAME']
AD_DIRECTORY_ID = os.environ['AD_DIRECTORY_ID']
AD_DOMAIN_NAME = os.environ['AD_DOMAIN_NAME']
AD_DNS_IP_1 = os.environ['AD_DNS_IP_1']
AD_DNS_IP_2 = os.environ['AD_DNS_IP_2']
AD_ADMIN_PASSWORD = os.environ['AD_ADMIN_PASSWORD']

def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    for record in event['Records']:
        if record['eventName'] == 'INSERT':
            new_image = record['dynamodb']['NewImage']
            
            employee_id = new_image['id']['S']
            name = new_image['name']['S']
            email = new_image['email']['S']
            username = new_image['username']['S']
            role = new_image['role']['S']
            department = new_image['department']['S']
            processed = new_image.get('processed', {}).get('BOOL', False)
            
            if processed:
                print(f"Employee {employee_id} already processed, skipping")
                continue
            
            print(f"Processing new employee: {name} ({username})")
            
            try:
                password = generate_password()
                print(f"Generated password for {username}")
                
                # Determine access level based on department/role
                access_level, ad_group = determine_access_level(department, role)
                print(f"Access level: {access_level}, AD Group: {ad_group}")
                
                # Create user in Active Directory
                ad_user_created = create_ad_user(username, name, password, ad_group)
                if not ad_user_created:
                    raise Exception(f"Failed to create AD user for {username}")
                
                print(f"Successfully created AD user: {username}")
                
                # Launch domain-joined virtual desktop
                instance_id, private_ip = launch_virtual_desktop(
                    employee_id, name, username, department, role, access_level
                )
                
                if not instance_id:
                    raise Exception(f"Failed to launch EC2 instance for {username}")
                
                print(f"Successfully launched EC2 instance: {instance_id} ({private_ip})")
                
                wait_for_instance_running(instance_id)
                
                # Send email with domain credentials
                send_email_success = send_credentials_email(
                    name, email, username, password, private_ip, access_level
                )
                
                if not send_email_success:
                    print(f"Warning: Failed to send email to {email}")
                
                update_employee_status(
                    employee_id, 
                    processed=True, 
                    instance_id=instance_id,
                    private_ip=private_ip,
                    access_level=access_level
                )
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'message': f'Successfully provisioned desktop for {username}',
                        'employee_id': employee_id,
                        'instance_id': instance_id,
                        'access_level': access_level,
                        'ad_group': ad_group
                    })
                }
                
            except Exception as e:
                print(f"Error: {str(e)}")
                return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}

def generate_password(length=12):
    """Generate a secure random password"""
    characters = string.ascii_letters + string.digits + "!@#$%"
    password = ''.join(random.choice(characters) for i in range(length))
    if not any(c.isupper() for c in password):
        password = password[:-1] + random.choice(string.ascii_uppercase)
    if not any(c.isdigit() for c in password):
        password = password[:-1] + random.choice(string.digits)
    return password

def determine_access_level(department, role):
    """
    Determine access level and AD group based on department and role
    Returns: (access_level, ad_group_ou_path)
    """
    dept_lower = department.lower()
    role_lower = role.lower()
    
    # Admin access: IT, Management
    if any(x in dept_lower for x in ['it', 'management', 'admin']):
        return 'admin', 'CN=InnovatechAdmins,OU=Groups,DC=innovatech,DC=local'
    if any(x in role_lower for x in ['manager', 'admin', 'director', 'cto', 'cio']):
        return 'admin', 'CN=InnovatechAdmins,OU=Groups,DC=innovatech,DC=local'
    
    # Developer access: Engineering, Development
    if any(x in dept_lower for x in ['engineering', 'development', 'devops', 'tech']):
        return 'developer', 'CN=InnovatechDevelopers,OU=Groups,DC=innovatech,DC=local'
    if any(x in role_lower for x in ['developer', 'engineer', 'programmer', 'architect']):
        return 'developer', 'CN=InnovatechDevelopers,OU=Groups,DC=innovatech,DC=local'
    
    # Default: Analyst
    return 'analyst', 'CN=InnovatechAnalysts,OU=Groups,DC=innovatech,DC=local'

def create_ad_user(username, full_name, password, ad_group):
    """
    Create user in AWS Managed Active Directory
    Note: AWS Managed AD uses a simplified API - we can't directly add to groups via API
    """
    try:
        # Split name for AD
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else username
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
        
        # Check if user already exists
        try:
            response = ds.describe_user(
                DirectoryId=AD_DIRECTORY_ID,
                SAMAccountName=username
            )
            print(f"User {username} already exists in AD")
            # Reset password for existing user
            ds.reset_user_password(
                DirectoryId=AD_DIRECTORY_ID,
                UserName=username,
                NewPassword=password
            )
            return True
        except ds.exceptions.UserDoesNotExistException:
            pass  # User doesn't exist, create it
        
        # Create new user in AD
        print(f"Creating AD user: {username}")
        ds.create_user(
            DirectoryId=AD_DIRECTORY_ID,
            SAMAccountName=username,
            Password=password,
            GivenName=first_name,
            Surname=last_name or username,
            DisplayName=full_name,
            EmailAddress=f"{username}@{AD_DOMAIN_NAME}"
        )
        
        print(f"Successfully created AD user: {username}")
        
        # Note: Group membership will be managed via Group Policy and OU placement
        # For full group management, would need custom PowerShell scripts or SSM
        
        return True
        
    except Exception as e:
        print(f"Error creating AD user: {str(e)}")
        return False

def launch_virtual_desktop(employee_id, name, username, department, role, access_level):
    """
    Launch EC2 virtual desktop with domain join configuration
    """
    try:
        print(f"Launching {access_level} desktop for {username}")
        
        # Role-based software packages
        if access_level == 'admin':
            software = "xfce4 xfce4-goodies xrdp firefox libreoffice vim git docker.io build-essential python3-pip nodejs npm htop net-tools realmd sssd adcli"
            description = "Full admin access with all development tools"
        elif access_level == 'developer':
            software = "xfce4 xfce4-goodies xrdp firefox vim git docker.io build-essential python3-pip nodejs npm realmd sssd adcli"
            description = "Development tools with limited admin access"
        else:  # analyst
            software = "xfce4 xfce4-goodies xrdp firefox libreoffice python3 vim realmd sssd adcli"
            description = "Standard office applications"
        
        # User data script for domain join
        user_data = f"""#!/bin/bash
set -e
exec > >(tee /var/log/user-data.log) 2>&1

echo "=== Starting provisioning for {username} - {access_level} ==="

# Update and install software
apt-get update
apt-get upgrade -y
apt-get install -y {software}

# Configure xrdp
echo "xfce4-session" > /etc/skel/.xsession
systemctl enable xrdp
systemctl start xrdp
ufw allow 3389/tcp || true

# Configure DNS to use AD DNS servers
echo "nameserver {AD_DNS_IP_1}" > /etc/resolv.conf
echo "nameserver {AD_DNS_IP_2}" >> /etc/resolv.conf
echo "search {AD_DOMAIN_NAME}" >> /etc/resolv.conf

# Make DNS changes persistent
cat > /etc/systemd/resolved.conf << DNSCONF
[Resolve]
DNS={AD_DNS_IP_1} {AD_DNS_IP_2}
Domains={AD_DOMAIN_NAME}
DNSCONF

systemctl restart systemd-resolved

# Install Kerberos client
DEBIAN_FRONTEND=noninteractive apt-get install -y krb5-user

# Configure Kerberos
cat > /etc/krb5.conf << KRBCONF
[libdefaults]
    default_realm = {AD_DOMAIN_NAME.upper()}
    dns_lookup_realm = true
    dns_lookup_kdc = true
    ticket_lifetime = 24h
    renew_lifetime = 7d
    forwardable = true

[realms]
    {AD_DOMAIN_NAME.upper()} = {{
        kdc = {AD_DNS_IP_1}
        kdc = {AD_DNS_IP_2}
        admin_server = {AD_DNS_IP_1}
    }}
KRBCONF

# Join domain
echo "{AD_ADMIN_PASSWORD}" | realm join -U Admin {AD_DOMAIN_NAME} --verbose

# Configure SSSD for AD authentication
cat > /etc/sssd/sssd.conf << SSSDCONF
[sssd]
services = nss, pam
config_file_version = 2
domains = {AD_DOMAIN_NAME}

[domain/{AD_DOMAIN_NAME}]
id_provider = ad
access_provider = ad
ad_domain = {AD_DOMAIN_NAME}
krb5_realm = {AD_DOMAIN_NAME.upper()}
cache_credentials = True
krb5_store_password_if_offline = True
default_shell = /bin/bash
fallback_homedir = /home/%u
SSSDCONF

chmod 600 /etc/sssd/sssd.conf
systemctl restart sssd

# Allow AD users to login via RDP
echo "session required pam_mkhomedir.so skel=/etc/skel/ umask=0022" >> /etc/pam.d/common-session

# Create role info file
mkdir -p /etc/innovatech
cat > /etc/innovatech/role-info.txt << ROLEINFO
===================================
INNOVATECH VIRTUAL DESKTOP
===================================
Hostname: $(hostname)
Domain: {AD_DOMAIN_NAME}
Access Level: {access_level.upper()}
Department: {department}
Role: {role}

Description: {description}

Login: Use domain credentials
Format: {AD_DOMAIN_NAME}\\username

For support: it@innovatech.com
===================================
ROLEINFO

# Install SSM Agent
snap install amazon-ssm-agent --classic || true
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service
systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service

echo "=== Provisioning completed for {username} ==="
"""

        # Launch instance
        response = ec2.run_instances(
            ImageId=AMI_ID,
            InstanceType='t3.medium',
            KeyName=KEY_NAME,
            IamInstanceProfile={
                'Arn': 'arn:aws:iam::511000088594:instance-profile/cs3-nca-virtual-desktop-profile'
            },
            MinCount=1,
            MaxCount=1,
            NetworkInterfaces=[{
                'SubnetId': SUBNET_ID,
                'DeviceIndex': 0,
                'AssociatePublicIpAddress': False,
                'Groups': [SECURITY_GROUP_ID]
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
                    {'Key': 'AccessLevel', 'Value': access_level},
                    {'Key': 'Domain', 'Value': AD_DOMAIN_NAME},
                    {'Key': 'DomainJoined', 'Value': 'true'},
                    {'Key': 'Purpose', 'Value': 'EmployeeDesktop'}
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
        return instance_id, private_ip
        
    except Exception as e:
        print(f"Error launching instance: {str(e)}")
        return None, None

def wait_for_instance_running(instance_id, max_attempts=30):
    for attempt in range(max_attempts):
        response = ec2.describe_instances(InstanceIds=[instance_id])
        state = response['Reservations'][0]['Instances'][0]['State']['Name']
        if state == 'running':
            return True
        time.sleep(10)
    return False

def send_credentials_email(name, email, username, password, private_ip, access_level):
    try:
        first_name = name.split()[0]
        
        access_descriptions = {
            'admin': 'Full administrative access - All tools and sudo privileges',
            'developer': 'Development environment - Dev tools with limited admin access',
            'analyst': 'Standard user access - Office applications only'
        }
        
        subject = f"Innovatech Virtual Desktop - {access_level.title()} Access"
        
        html_body = f"""<html><body style="font-family: Arial;">
<div style="max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: #2563eb; color: white; padding: 20px; text-align: center;">
        <h1>Welcome to Innovatech!</h1>
    </div>
    
    <div style="background: #f9fafb; padding: 30px; margin-top: 20px;">
        <p>Hi {first_name},</p>
        <p>Your <strong>{access_level.upper()}</strong> virtual desktop with centralized Active Directory authentication is ready!</p>
        
        <div style="background: white; padding: 20px; border-left: 4px solid #2563eb; margin: 20px 0;">
            <h3>🔐 Domain Login Credentials</h3>
            <p><strong>Domain:</strong> <code>{AD_DOMAIN_NAME}</code></p>
            <p><strong>Username:</strong> <code>{username}</code></p>
            <p><strong>Full Login:</strong> <code>{AD_DOMAIN_NAME}\\{username}</code></p>
            <p><strong>Password:</strong> <code>{password}</code></p>
            <p><strong>Desktop IP:</strong> <code>{private_ip}:3389</code></p>
            <p><strong>VPN Server:</strong> <code>{OPENVPN_SERVER_IP}</code></p>
            <p style="font-size: 12px; color: #666; margin-top: 10px;">Access Level: {access_level.title()}<br>{access_descriptions[access_level]}</p>
        </div>
        
        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0;">
            <strong>⚠️ Important:</strong> Desktop may take 10-15 minutes to fully boot and join the domain.
        </div>
        
        <h3>📋 Connection Steps:</h3>
        <ol>
            <li><strong>Connect to VPN</strong>
                <ul><li>Download OpenVPN Connect</li><li>Import VPN config from IT</li><li>Connect to VPN</li></ul>
            </li>
            <li><strong>Open Remote Desktop</strong>
                <ul><li>Server: <code>{private_ip}:3389</code></li><li>Login format: <code>{AD_DOMAIN_NAME}\\{username}</code></li><li>Password: (from above)</li></ul>
            </li>
        </ol>
        
        <div style="background: #e0f2fe; border-left: 4px solid #0284c7; padding: 15px; margin: 20px 0;">
            <strong> Single Sign-On:</strong> These credentials work across ALL company systems and virtual desktops. Change your password once, it updates everywhere!
        </div>
        
        <p style="margin-top: 30px;">Questions? Contact IT: <a href="mailto:it@innovatech.com">it@innovatech.com</a></p>
        <p>Welcome aboard!<br><strong>The Innovatech IT Team</strong></p>
    </div>
</div>
</body></html>"""
        
        text_body = f"""Welcome to Innovatech!

Hi {first_name},

Your {access_level.upper()} virtual desktop is ready with centralized Active Directory authentication!

Domain Login Credentials:
Domain: {AD_DOMAIN_NAME}
Username: {username}
Full Login: {AD_DOMAIN_NAME}\\{username}
Password: {password}
Desktop: {private_ip}:3389
VPN: {OPENVPN_SERVER_IP}

Connection Steps:
1. Connect to VPN (OpenVPN Connect)
2. RDP to {private_ip}:3389
3. Login with: {AD_DOMAIN_NAME}\\{username}

Single Sign-On: These credentials work across all company systems!

Contact IT: it@innovatech.com
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
        return True
    except Exception as e:
        print(f"Email error: {str(e)}")
        return False

def update_employee_status(employee_id, processed=True, instance_id=None, private_ip=None, access_level=None):
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
        
        if access_level:
            update_expr += ', access_level = :access'
            expr_values[':access'] = {'S': access_level}
        
        dynamodb.update_item(
            TableName=DYNAMODB_TABLE,
            Key={'id': {'S': employee_id}},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values
        )
        return True
    except Exception as e:
        print(f"Update error: {str(e)}")
        return False