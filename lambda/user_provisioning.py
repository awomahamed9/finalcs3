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

# Environment variables
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
SES_SENDER_EMAIL = os.environ['SES_SENDER_EMAIL']
OPENVPN_SERVER_IP = os.environ['OPENVPN_SERVER_IP']
SUBNET_ID = os.environ['SUBNET_ID']
SECURITY_GROUP_ID = os.environ['SECURITY_GROUP_ID']
AMI_ID = os.environ['AMI_ID']
KEY_NAME = os.environ['KEY_NAME']
IAM_INSTANCE_PROFILE = os.environ.get('IAM_INSTANCE_PROFILE', 'cs3-nca-virtual-desktop-profile')

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
            print(f"Department: {department}, Role: {role}")
            
            try:
                password = generate_password()
                print(f"Generated password for {username}")
                
                # Determine role based on department
                assigned_role = determine_role(department)
                print(f"Assigned RBAC role: {assigned_role}")
                
                instance_id, private_ip = launch_virtual_desktop(
                    employee_id, name, username, password, department, assigned_role
                )
                
                if not instance_id:
                    raise Exception(f"Failed to launch EC2 instance for {username}")
                
                print(f"Successfully launched EC2: {instance_id} ({private_ip})")
                
                wait_for_instance_running(instance_id)
                
                send_email_success = send_credentials_email(
                    name, email, username, password, private_ip, assigned_role
                )
                
                if not send_email_success:
                    print(f"Warning: Failed to send email to {email}")
                
                update_employee_status(
                    employee_id, 
                    processed=True, 
                    instance_id=instance_id,
                    private_ip=private_ip,
                    assigned_role=assigned_role
                )
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'message': f'Successfully provisioned desktop for {username}',
                        'employee_id': employee_id,
                        'instance_id': instance_id,
                        'role': assigned_role
                    })
                }
                
            except Exception as e:
                print(f"Error: {str(e)}")
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

def determine_role(department):
    """
    Determine RBAC role based on department
    
    Returns: 'admin', 'developer', or 'analyst'
    """
    dept_lower = department.lower()
    
    if dept_lower in ['it', 'infrastructure', 'devops', 'management']:
        return 'admin'
    elif dept_lower in ['engineering', 'development', 'software']:
        return 'developer'
    else:
        return 'analyst'

def launch_virtual_desktop(employee_id, name, username, password, department, role):
    """
    Launch EC2 instance with RBAC permissions and SSM enrollment
    """
    try:
        # Role-based configuration
        role_configs = {
            'admin': {
                'sudo_access': True,
                'packages': 'firefox libreoffice vim git docker.io build-essential python3-pip nodejs npm htop net-tools',
                'group': 'sudo',
                'description': 'Full administrative access with all development tools'
            },
            'developer': {
                'sudo_access': True,
                'packages': 'firefox vim git docker.io build-essential python3-pip nodejs npm',
                'group': 'developers',
                'description': 'Development environment with sudo access for dev tools'
            },
            'analyst': {
                'sudo_access': False,
                'packages': 'firefox libreoffice python3-pip vim',
                'group': 'analysts',
                'description': 'Standard user access with office and analysis tools'
            }
        }
        
        config = role_configs.get(role, role_configs['analyst'])
        
        # Create user data script with RBAC + SSM
        user_data = f"""#!/bin/bash
set -e

# Log everything
exec > >(tee /var/log/user-data.log)
exec 2>&1

echo "=========================================="
echo "Starting Virtual Desktop Provisioning"
echo "Employee: {name}"
echo "Username: {username}"
echo "Role: {role.upper()}"
echo "=========================================="

# Update system
echo "Updating system packages..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

# Install XFCE desktop environment
echo "Installing desktop environment..."
DEBIAN_FRONTEND=noninteractive apt-get install -y xfce4 xfce4-goodies xfce4-terminal

# Install xrdp for RDP access
echo "Installing xrdp..."
DEBIAN_FRONTEND=noninteractive apt-get install -y xrdp

# Configure xrdp
echo "Configuring xrdp..."
echo "xfce4-session" > /etc/skel/.xsession
systemctl enable xrdp
systemctl start xrdp

# Install role-specific software
echo "Installing role-specific packages for {role}..."
DEBIAN_FRONTEND=noninteractive apt-get install -y {config['packages']}

# Configure firewall
echo "Configuring firewall..."
ufw allow 3389/tcp || true
ufw --force enable || true

# Create role-specific group
echo "Creating role group: {config['group']}"
groupadd {config['group']} 2>/dev/null || true

# Create user
echo "Creating user: {username}"
useradd -m -s /bin/bash -c "{name}" -G {config['group']} {username}

# Set password
echo "Setting password..."
echo '{username}:{password}' | chpasswd

# Configure sudo access
{'echo "' + username + ' ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/' + username if config['sudo_access'] else 'echo "# No sudo access for ' + username + '"'}
{'chmod 0440 /etc/sudoers.d/' + username if config['sudo_access'] else ''}

# Set up desktop environment
echo "Configuring desktop for user..."
mkdir -p /home/{username}/.config
echo 'xfce4-session' > /home/{username}/.xsession
chown -R {username}:{username} /home/{username}

# Create role information file
cat > /home/{username}/WELCOME.txt << 'ROLEINFO'
========================================
INNOVATECH VIRTUAL DESKTOP
========================================

Employee: {name}
Username: {username}
Role: {role.upper()}
Department: {department}

Access Level: {config['description']}
Sudo Access: {'YES' if config['sudo_access'] else 'NO'}

Installed Software:
{config['packages'].replace(' ', ', ')}

For support, contact IT: it@innovatech.com
========================================
ROLEINFO

chown {username}:{username} /home/{username}/WELCOME.txt

# Disable password expiration
chage -I -1 -m 0 -M 99999 -E -1 {username}

# Install and configure SSM Agent for device enrollment
echo "Installing AWS SSM Agent..."
snap install amazon-ssm-agent --classic 2>/dev/null || {{
    # Fallback if snap not available
    wget https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_amd64/amazon-ssm-agent.deb
    dpkg -i amazon-ssm-agent.deb
    systemctl enable amazon-ssm-agent
    systemctl start amazon-ssm-agent
}}

# Enable and start SSM agent
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || systemctl enable amazon-ssm-agent
systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || systemctl start amazon-ssm-agent

# Verify SSM agent is running
echo "Verifying SSM Agent status..."
systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || systemctl status amazon-ssm-agent

# Create desktop shortcuts
echo "Creating desktop shortcuts..."
mkdir -p /home/{username}/Desktop
cat > /home/{username}/Desktop/Welcome.desktop << 'DESKTOP'
[Desktop Entry]
Type=Application
Name=Welcome Info
Exec=xfce4-terminal -e "cat /home/{username}/WELCOME.txt; read -p 'Press Enter to close'"
Icon=dialog-information
DESKTOP
chmod +x /home/{username}/Desktop/Welcome.desktop
chown {username}:{username} /home/{username}/Desktop/Welcome.desktop

# Log role assignment
echo "=========================================="
echo "Provisioning completed successfully!"
echo "User: {username}"
echo "Role: {role}"
echo "Sudo: {'YES' if config['sudo_access'] else 'NO'}"
echo "SSM Agent: INSTALLED"
echo "Desktop: READY"
echo "=========================================="
"""

        # Launch EC2 instance with IAM instance profile for SSM
        print(f"Launching instance with profile: {IAM_INSTANCE_PROFILE}")
        
        response = ec2.run_instances(
            ImageId=AMI_ID,
            InstanceType='t3.medium',
            KeyName=KEY_NAME,
            IamInstanceProfile={'Name': IAM_INSTANCE_PROFILE},  # Critical for SSM!
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
                    {'Key': 'RBACRole', 'Value': role},
                    {'Key': 'Purpose', 'Value': 'EmployeeDesktop'},
                    {'Key': 'DeviceEnrolled', 'Value': 'SSM'},
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
        
        print(f"Instance launched: {instance_id}")
        print(f"Private IP: {private_ip}")
        print(f"Role configured: {role}")
        print(f"SSM Profile attached: {IAM_INSTANCE_PROFILE}")
        
        return instance_id, private_ip
        
    except Exception as e:
        print(f"Error launching instance: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, None

def wait_for_instance_running(instance_id, max_attempts=30):
    """Wait for EC2 instance to reach running state"""
    for attempt in range(max_attempts):
        try:
            response = ec2.describe_instances(InstanceIds=[instance_id])
            state = response['Reservations'][0]['Instances'][0]['State']['Name']
            print(f"Instance {instance_id} state: {state} (attempt {attempt+1}/{max_attempts})")
            
            if state == 'running':
                print(f"Instance {instance_id} is now running")
                return True
            
            time.sleep(10)
        except Exception as e:
            print(f"Error checking instance state: {str(e)}")
    
    print(f"Timeout waiting for instance {instance_id}")
    return False

def send_credentials_email(name, email, username, password, private_ip, role):
    """Send welcome email with credentials and role information"""
    try:
        first_name = name.split()[0]
        
        # Role-specific welcome messages
        role_messages = {
            'admin': {
                'title': 'System Administrator',
                'access': 'Full administrative access with sudo privileges',
                'tools': 'All development and system administration tools'
            },
            'developer': {
                'title': 'Software Developer',
                'access': 'Developer access with sudo for development tools',
                'tools': 'Git, Docker, Node.js, Python, Build tools'
            },
            'analyst': {
                'title': 'Data Analyst',
                'access': 'Standard user access (no sudo)',
                'tools': 'Firefox, LibreOffice, Python, Analysis tools'
            }
        }
        
        role_info = role_messages.get(role, role_messages['analyst'])
        
        subject = f"Welcome to Innovatech - Your Virtual Desktop ({role_info['title']})"
        
        html_body = f"""<html>
<head>
<style>
body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
.container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
.header {{ background: #2563eb; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
.content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 8px 8px; }}
.credentials {{ background: white; padding: 20px; border-left: 4px solid #2563eb; margin: 20px 0; border-radius: 4px; }}
.role-badge {{ display: inline-block; background: #10b981; color: white; padding: 8px 16px; border-radius: 20px; font-weight: bold; margin: 10px 0; }}
.credential-item {{ margin: 10px 0; }}
.label {{ font-weight: bold; color: #374151; }}
.value {{ font-family: monospace; background: #f3f4f6; padding: 5px 10px; border-radius: 4px; }}
.warning {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0; border-radius: 4px; }}
.info {{ background: #dbeafe; border-left: 4px solid #2563eb; padding: 15px; margin: 20px 0; border-radius: 4px; }}
.footer {{ text-align: center; margin-top: 30px; color: #6b7280; font-size: 12px; }}
ol {{ padding-left: 20px; }}
li {{ margin: 10px 0; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Welcome to Innovatech!</h1>
    <p style="margin:0;">Your dedicated virtual desktop is ready</p>
  </div>
  
  <div class="content">
    <p>Hi {first_name},</p>
    
    <p>Your dedicated virtual desktop has been provisioned with role-based access control.</p>
    
    <div class="info">
      <strong>🎯 Your Role:</strong>
      <div class="role-badge">{role.upper()} - {role_info['title']}</div>
      <p><strong>Access Level:</strong> {role_info['access']}</p>
      <p><strong>Available Tools:</strong> {role_info['tools']}</p>
    </div>
    
    <div class="credentials">
      <h3>Your Login Credentials</h3>
      <div class="credential-item">
        <span class="label">Username:</span>
        <span class="value">{username}</span>
      </div>
      <div class="credential-item">
        <span class="label">Password:</span>
        <span class="value">{password}</span>
      </div>
      <div class="credential-item">
        <span class="label">VPN Server:</span>
        <span class="value">{OPENVPN_SERVER_IP}</span>
      </div>
      <div class="credential-item">
        <span class="label">Your Desktop:</span>
        <span class="value">{private_ip}:3389</span>
      </div>
    </div>
    
    <div class="warning">
      <strong>⚠️ Important:</strong> Save these credentials securely. Your desktop may take 5-10 minutes to fully boot up.
    </div>
    
    <h3>How to Connect:</h3>
    <ol>
      <li><strong>Connect to VPN</strong>
        <ul>
          <li>Download OpenVPN Connect: <a href="https://openvpn.net/client/">openvpn.net/client</a></li>
          <li>Contact IT for your VPN config file (.ovpn)</li>
          <li>Import and connect to VPN</li>
        </ul>
      </li>
      <li><strong>Connect to Your Desktop</strong>
        <ul>
          <li>Open Microsoft Remote Desktop client</li>
          <li>Server: <code>{private_ip}:3389</code></li>
          <li>Username: <code>{username}</code></li>
          <li>Password: <code>{password}</code></li>
        </ul>
      </li>
      <li><strong>Welcome File</strong>
        <ul>
          <li>Check your desktop for WELCOME.txt with role details</li>
        </ul>
      </li>
    </ol>
    
    <p style="margin-top: 30px;">Questions? Contact IT: <a href="mailto:it@innovatech.com">it@innovatech.com</a></p>
    
    <p>Welcome aboard!</p>
    <p><strong>The Innovatech IT Team</strong></p>
  </div>
  
  <div class="footer">
    <p>Automated Employee Provisioning System | Innovatech Solutions</p>
    <p>© {datetime.now().year} - Confidential</p>
  </div>
</div>
</body>
</html>"""
        
        text_body = f"""Welcome to Innovatech!

Hi {first_name},

Your dedicated virtual desktop is ready!

YOUR ROLE: {role.upper()} - {role_info['title']}
Access Level: {role_info['access']}
Tools: {role_info['tools']}

LOGIN CREDENTIALS:
Username: {username}
Password: {password}
VPN Server: {OPENVPN_SERVER_IP}
Your Desktop: {private_ip}:3389

IMPORTANT: Save these credentials. Desktop may take 5-10 minutes to boot.

HOW TO CONNECT:
1. Connect to VPN:
   - Download OpenVPN Connect
   - Import .ovpn file from IT
   - Connect to VPN

2. Connect to Desktop:
   - Open RDP client
   - Server: {private_ip}:3389
   - Login with your credentials

Check WELCOME.txt on your desktop for role details.

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
        
        print(f"Email sent to {email} with role info: {role}")
        return True
        
    except Exception as e:
        print(f"Email error: {str(e)}")
        return False

def update_employee_status(employee_id, processed=True, instance_id=None, private_ip=None, assigned_role=None):
    """Update employee record with instance info and role"""
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
        
        print(f"Updated employee {employee_id}: processed={processed}, role={assigned_role}")
        return True
        
    except Exception as e:
        print(f"Update error: {str(e)}")
        return False