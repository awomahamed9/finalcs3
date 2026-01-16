<powershell>
# Log everything
Start-Transcript -Path C:\userdata-log.txt

Write-Host "=========================================="
Write-Host "Starting AD Automation Server Setup"
Write-Host "=========================================="

# Wait for network
Start-Sleep -Seconds 30

# Install AWS Tools
Write-Host "Installing AWS PowerShell Tools..."
Install-PackageProvider -Name NuGet -Force -Scope AllUsers
Install-Module -Name AWS.Tools.Installer -Force -Scope AllUsers
Install-AWSToolsModule -Name AWS.Tools.Common,AWS.Tools.SecretsManager,AWS.Tools.SQS -Force

# Set DNS to AD domain controllers
Write-Host "Configuring DNS to point to AD..."
$adapter = Get-NetAdapter | Where-Object {$_.Status -eq "Up"} | Select-Object -First 1
Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses "${dns_ip_1}","${dns_ip_2}"

Write-Host "DNS configured: ${dns_ip_1}, ${dns_ip_2}"

# Get Admin credentials from Secrets Manager
Write-Host "Retrieving AD admin credentials..."
$secretJson = Get-SECSecretValue -SecretId "${secret_arn}" -Region ${aws_region}
$secret = $secretJson.SecretString | ConvertFrom-Json
$password = ConvertTo-SecureString $secret.password -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential("Admin@${directory_name}", $password)

# Wait for AD to be fully available before joining domain
Write-Host "Waiting for AD to be ready..."
$maxAttempts = 60
$attempt = 0
$adReady = $false

while (-not $adReady -and $attempt -lt $maxAttempts) {
    try {
        $attempt++
        Write-Host "Attempt $attempt/$maxAttempts - Testing AD connectivity..."
        $result = Test-NetConnection -ComputerName "${dns_ip_1}" -Port 389 -InformationLevel Quiet
        if ($result) {
            Write-Host "AD is responding!"
            $adReady = $true
        } else {
            Write-Host "AD not ready yet, waiting 60 seconds..."
            Start-Sleep -Seconds 60
        }
    } catch {
        Write-Host "Error testing AD: $_"
        Start-Sleep -Seconds 60
    }
}

if (-not $adReady) {
    Write-Host "WARNING: AD did not become ready in time. Domain join may fail."
    Write-Host "You may need to manually join the domain later."
} else {
    # Join domain
    Write-Host "Joining domain ${directory_name}..."
    try {
        Add-Computer -DomainName "${directory_name}" -Credential $credential -Restart -Force
        Write-Host "Domain join initiated - server will restart"
    } catch {
        Write-Host "ERROR: Domain join failed: $_"
        Write-Host "Check AD status in AWS Console and manually join later"
    }
}

Write-Host "=========================================="
Write-Host "Setup script completed"
Write-Host "=========================================="

Stop-Transcript
</powershell>
