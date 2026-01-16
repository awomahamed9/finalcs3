import json
import boto3
import os
import random
import string
import base64
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
            
            try:
                password = generate_password()
                print(f"Generated password for {username}")
                
                # Publish to SNS for AD user creation
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Message=json.dumps({
                        'employee_id': employee_id,
                        'name': name,
                        'username': username,
                        'password': password,
                        'email': email,
                        'role': role,
                        'department': department
                    }),
                    Subject=f'Create AD User: {username}'
                )
                print(f"Published to SNS for {username}")
                
                # Launch Windows virtual desktop
                instance_id, private_ip = launch_windows_desktop(
                    employee_id, name, username, department, role
                )
                
                if not instance_id:
                    raise Exception(f"Failed to launch Windows desktop for {username}")
                
                print(f" Launched Windows desktop: {instance_id} ({private_ip})")
                
                # Send credentials email
                send_credentials_email(name, email, username, password, private_ip, role)
                
                # Update employee status
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
                        'message': f'Successfully provisioned Windows desktop for {username}',
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

def launch_windows_desktop(employee_id, name, username, department, role):
    """Launch Windows domain-joined virtual desktop with RBAC and Fixes"""
    try:
        
        user_data_script = f"""<powershell>
Start-Transcript -Path "C:\\ProgramData\\Amazon\\EC2Launch\\log\\user-data-transcript.log"

Write-Host "=== Starting Windows Desktop Setup for {username} ==="

# 1.  Configure DNS (Crucial for Domain Join)
$adapter = Get-NetAdapter | Where-Object {{ $_.Status -eq "Up" }} | Select-Object -First 1
Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses "10.0.11.44","10.0.12.42"
Write-Host "DNS Configured"

# 2.  Wait for AD Connectivity
$ready = $false
for ($i=1; $i -le 30; $i++) {{
    if (Test-NetConnection -ComputerName 10.0.11.44 -Port 389 -InformationLevel Quiet) {{
        $ready = $true
        break
    }}
    Start-Sleep -Seconds 10
}}

if ($ready) {{
    Write-Host "Joining domain..."
    $password = ConvertTo-SecureString "Student123" -AsPlainText -Force
    $credential = New-Object System.Management.Automation.PSCredential("Admin@innovatech.local", $password)
    
    try {{
        # A. Join Domain
        Add-Computer -DomainName "innovatech.local" -Credential $credential -Force
        
        # RBAC 
        Write-Host "Applying Department Policy: {department}"
        
        # General: Create Info folder for everyone
        New-Item -Path "C:\\" -Name "CompanyData" -ItemType "directory" -ErrorAction SilentlyContinue
        Set-Content -Path "C:\\CompanyData\\UserContext.txt" -Value "User: {username}`r`nRole: {role}`r`nDept: {department}"

        if ("{department}" -eq "HR") {{
            # HR CONFIGURATION
            Write-Host "Setting up HR Environment..."
            
            # 1. Create Confidential Folder
            New-Item -Path "C:\\" -Name "HR_Confidential" -ItemType "directory"
            Set-Content -Path "C:\\HR_Confidential\\Payroll_Templates.txt" -Value "Confidential Payroll Data"
            
            # 2. Add Security Policy to Desktop (Visual "Realism")
            $desktopPath = "C:\\Users\\Public\\Desktop\\IT_Security_Policy.txt"
            $policyText = "WARNING: RESTRICTED ACCESS`r`n`r`nAs an HR employee, you are restricted from installing unauthorized software.`r`nAll activity is monitored.`r`n`r`n- IT Security"
            Set-Content -Path $desktopPath -Value $policyText
            
            # 3. Dummy Application
            Set-Content -Path "C:\\Users\\Public\\Desktop\\Payroll_App.lnk" -Value "Dummy Link"
        }}
        elseif ("{department}" -eq "IT") {{
            # IT CONFIGURATION
            Write-Host "Setting up IT Environment..."
            
            # 1. Install Admin Tools (Real Feature!)
            Install-WindowsFeature RSAT-AD-PowerShell -IncludeAllSubFeature
            
            # 2. Create Scripts Folder
            New-Item -Path "C:\\" -Name "AdminScripts" -ItemType "directory"
            Set-Content -Path "C:\\AdminScripts\\readme.txt" -Value "PowerShell Admin Tools Installed"
        }}
        else {{
            # STANDARD USER
            Write-Host "Standard Setup Applied"
            Set-Content -Path "C:\\Users\\Public\\Desktop\\Welcome.txt" -Value "Welcome to Innovatech!"
        }}
        # ---------------------------

        # to Disable NLA 
        (Get-WmiObject -class "Win32_TSGeneralSetting" -Namespace root\\cimv2\\terminalservices -Filter "TerminalName='RDP-tcp'").SetUserAuthenticationRequired(0)

        # Grant RDP Access to domain users
        for ($k=1; $k -le 5; $k++) {{
            try {{
                Add-LocalGroupMember -Group "Remote Desktop Users" -Member "innovatech\\Domain Users" -ErrorAction Stop
                Write-Host "Success: Domain Users added to RDP group."
                break
            }} catch {{
                Start-Sleep -Seconds 5
            }}
        }}

        # D. Restart
        Restart-Computer -Force
        
    }} catch {{
        Write-Host "CRITICAL ERROR: $_"
    }}
}}

Stop-Transcript
</powershell>
<persist>true</persist>
"""
        #  Base64 Encode this is required for Windows
        encoded_user_data = base64.b64encode(user_data_script.encode("ascii")).decode("ascii")

        # Get AMI
        print("Finding Windows Server 2022 AMI...")
        windows_images = ec2.describe_images(
            Owners=['amazon'],
            Filters=[
                {'Name': 'name', 'Values': ['Windows_Server-2022-English-Full-Base-*']},
                {'Name': 'state', 'Values': ['available']}
            ]
        )['Images']
        
        windows_images.sort(key=lambda x: x['CreationDate'], reverse=True)
        ami_id = windows_images[0]['ImageId']
        
        # Launch
        response = ec2.run_instances(
            ImageId=ami_id,
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
            UserData=encoded_user_data,
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [
                    {'Key': 'Name', 'Value': f'windows-desktop-{username}'},
                    {'Key': 'Employee', 'Value': name},
                    {'Key': 'EmployeeId', 'Value': employee_id},
                    {'Key': 'Department', 'Value': department},
                    {'Key': 'Role', 'Value': role},
                    {'Key': 'OS', 'Value': 'Windows'},
                    {'Key': 'DomainJoined', 'Value': 'True'},
                    {'Key': 'Project', 'Value': 'cs3-nca'}
                ]
            }],
            BlockDeviceMappings=[{
                'DeviceName': '/dev/sda1',
                'Ebs': {
                    'VolumeSize': 50,
                    'VolumeType': 'gp3',
                    'DeleteOnTermination': True,
                    'Encrypted': True
                }
            }]
        )
        
        instance_id = response['Instances'][0]['InstanceId']
        private_ip = response['Instances'][0]['PrivateIpAddress']
        
        print(f"Launched Windows desktop: {instance_id} at {private_ip}")
        return instance_id, private_ip
        
    except Exception as e:
        print(f"Error launching Windows desktop: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, None

def send_credentials_email(name, email, username, password, private_ip, role):
    """Send welcome email with Windows desktop credentials"""
    try:
        first_name = name.split()[0]
        
        subject = "Welcome to Innovatech - Your Windows Desktop"
        
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
    <p>Your Windows desktop is ready</p>
  </div>
  
  <div class="content">
    <p>Hi {first_name},</p>
    
    <p>Your Windows virtual desktop has been provisioned and is being joined to the innovatech.local domain.</p>
    
    <div class="credentials">
      <h3>Your Login Credentials</h3>
      <div class="credential-item">
        <span class="label">Domain:</span>
        <span class="value">innovatech.local</span>
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
      <strong>Important:</strong> Your Windows desktop takes 10-15 minutes to boot and join the domain. Please wait before connecting.
    </div>
    
    <h3>How to Connect:</h3>
    <ol>
      <li><strong>Connect to VPN first</strong> (contact IT for VPN config file)</li>
      <li><strong>Open Remote Desktop:</strong>
        <ul>
          <li>Windows: Search for "Remote Desktop Connection"</li>
          <li>Mac: Download "Microsoft Remote Desktop" from App Store</li>
        </ul>
      </li>
      <li><strong>Computer:</strong> {private_ip}</li>
      <li><strong>Login options:</strong>
        <ul>
          <li>Username: <code>{username}</code></li>
          <li>Or: <code>innovatech\\{username}</code></li>
          <li>Or: <code>{username}@innovatech.local</code></li>
          <li>Password: <code>{password}</code></li>
        </ul>
      </li>
    </ol>
    
    <p><strong>First Login:</strong> You can change your password after first login using Ctrl+Alt+End → Change Password</p>
    
    <p>Questions? Contact IT: <a href="mailto:it@innovatech.com">it@innovatech.com</a></p>
    
    <p>Welcome aboard!</p>
    <p><strong>The Innovatech IT Team</strong></p>
  </div>
</div>
</body>
</html>"""
        
        text_body = f"""Welcome to Innovatech!

Hi {first_name},

Your Windows virtual desktop is ready!

CREDENTIALS:
Domain: innovatech.local
Username: {username}
Password: {password}
Desktop: {private_ip}:3389
VPN: {OPENVPN_SERVER_IP}

IMPORTANT: Wait 10-15 minutes for Windows to boot and join domain.

HOW TO CONNECT:
1. Connect to VPN first
2. Open Remote Desktop
3. Computer: {private_ip}
4. Login: {username} or innovatech\\{username}
5. Password: {password}

You can change your password after first login (Ctrl+Alt+End).

Questions? IT: it@innovatech.com

Welcome!
Innovatech IT Team
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
        
        print(f" Email sent to {email}")
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


        