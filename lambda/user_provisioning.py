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
                
                instance_id, private_ip = launch_virtual_desktop(
                    employee_id, name, username, password, department
                )
                
                if not instance_id:
                    raise Exception(f"Failed to launch EC2 instance for {username}")
                
                print(f"Successfully launched EC2 instance: {instance_id} ({private_ip})")
                
                wait_for_instance_running(instance_id)
                
                send_email_success = send_credentials_email(
                    name, email, username, password, private_ip
                )
                
                if not send_email_success:
                    print(f"Warning: Failed to send email to {email}")
                
                update_employee_status(
                    employee_id, 
                    processed=True, 
                    instance_id=instance_id,
                    private_ip=private_ip
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
                return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}

def generate_password(length=12):
    characters = string.ascii_letters + string.digits + "!@#$%"
    password = ''.join(random.choice(characters) for i in range(length))
    if not any(c.isupper() for c in password):
        password = password[:-1] + random.choice(string.ascii_uppercase)
    if not any(c.isdigit() for c in password):
        password = password[:-1] + random.choice(string.digits)
    return password

def launch_virtual_desktop(employee_id, name, username, password, department):
    try:
        user_data = f"""#!/bin/bash
set -e
apt-get update
apt-get upgrade -y
apt-get install -y xfce4 xfce4-goodies xrdp firefox libreoffice vim git
echo "xfce4-session" > /etc/skel/.xsession
systemctl enable xrdp
systemctl start xrdp
ufw allow 3389/tcp || true
useradd -m -s /bin/bash -c '{name}' {username}
echo '{username}:{password}' | chpasswd
echo 'xfce4-session' > /home/{username}/.xsession
chown {username}:{username} /home/{username}/.xsession
chage -I -1 -m 0 -M 99999 -E -1 {username}
"""

        response = ec2.run_instances(
            ImageId=AMI_ID,
            InstanceType='t3.medium',
            KeyName=KEY_NAME,
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
                    {'Key': 'Department', 'Value': department}
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

def send_credentials_email(name, email, username, password, private_ip):
    try:
        first_name = name.split()[0]
        subject = "Welcome to Innovatech - Your Virtual Desktop"
        
        html_body = f"""<html><body>
<h2>Welcome {first_name}!</h2>
<p>Your dedicated virtual desktop is ready.</p>
<h3>Login Credentials:</h3>
<ul>
<li><b>Username:</b> {username}</li>
<li><b>Password:</b> {password}</li>
<li><b>VPN Server:</b> {OPENVPN_SERVER_IP}</li>
<li><b>Desktop:</b> {private_ip}:3389</li>
</ul>
<p><b>Steps to Connect:</b></p>
<ol>
<li>Connect to VPN (OpenVPN)</li>
<li>Use RDP client to connect to {private_ip}:3389</li>
<li>Login with your credentials</li>
</ol>
<p>Contact IT for your VPN configuration file.</p>
</body></html>"""
        
        text_body = f"""Welcome {first_name}!

Your dedicated virtual desktop is ready.

Login Credentials:
Username: {username}
Password: {password}
VPN Server: {OPENVPN_SERVER_IP}
Desktop: {private_ip}:3389

Steps:
1. Connect to VPN
2. RDP to {private_ip}:3389
3. Login with credentials

Contact IT for VPN config.
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

def update_employee_status(employee_id, processed=True, instance_id=None, private_ip=None):
    try:
        update_expr = 'SET processed = :proc, processed_at = :time'
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
        
        dynamodb.update_item(
            TableName=DYNAMODB_TABLE,
            Key={'id': {'S': employee_id}},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values
        )
        return True
    except Exception as e:
        print(f"Update error: {str(e)}")
        return False