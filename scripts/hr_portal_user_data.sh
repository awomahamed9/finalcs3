#!/bin/bash
set -e

# Variables from Terraform
DYNAMODB_TABLE="${dynamodb_table_name}"
AWS_REGION="${aws_region}"
ADMIN_USERNAME="${admin_username}"
ADMIN_PASSWORD="${admin_password}"

# Update system
yum update -y

# Install Docker
amazon-linux-extras install docker -y
systemctl enable docker
systemctl start docker

# Add ec2-user to docker group
usermod -a -G docker ec2-user

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create application directory
mkdir -p /opt/hr-portal
cd /opt/hr-portal

# Create package.json
cat > package.json << 'PKGJSON'
{
  "name": "innovatech-hr-portal",
  "version": "1.0.0",
  "description": "HR Portal for Employee Management",
  "main": "server.js",
  "scripts": {
    "start": "node server.js"
  },
  "dependencies": {
    "express": "^4.18.2",
    "aws-sdk": "^2.1490.0",
    "uuid": "^9.0.1",
    "body-parser": "^1.20.2"
  }
}
PKGJSON

# Create server.js (using cat with base64 to avoid quote issues)
cat > server.js << 'ENDOFSERVER'
const express = require('express');
const bodyParser = require('body-parser');
const AWS = require('aws-sdk');
const { v4: uuidv4 } = require('uuid');

const app = express();
const PORT = 3000;

AWS.config.update({ region: process.env.AWS_REGION || 'eu-central-1' });
const dynamodb = new AWS.DynamoDB.DocumentClient();
const TABLE_NAME = process.env.DYNAMODB_TABLE;

const ADMIN_USERNAME = process.env.ADMIN_USERNAME || 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'Innovatech2024!';

const basicAuth = (req, res, next) => {
  const authHeader = req.headers.authorization;
  if (!authHeader) {
    res.setHeader('WWW-Authenticate', 'Basic realm="HR Portal"');
    return res.status(401).send('Authentication required');
  }
  const auth = Buffer.from(authHeader.split(' ')[1], 'base64').toString().split(':');
  const username = auth[0];
  const password = auth[1];
  if (username === ADMIN_USERNAME && password === ADMIN_PASSWORD) {
    next();
  } else {
    res.setHeader('WWW-Authenticate', 'Basic realm="HR Portal"');
    return res.status(401).send('Invalid credentials');
  }
};

app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));
app.use((req, res, next) => {
  if (req.path === '/health') {
    return next();
  }
  basicAuth(req, res, next);
});
app.use(express.static('public'));

app.get('/health', (req, res) => {
  res.json({ status: 'healthy', timestamp: new Date().toISOString() });
});

app.get('/api/employees', async (req, res) => {
  try {
    const params = { TableName: TABLE_NAME };
    const result = await dynamodb.scan(params).promise();
    res.json(result.Items);
  } catch (error) {
    console.error('Error:', error);
    res.status(500).json({ error: 'Failed to fetch employees' });
  }
});

app.post('/api/employees', async (req, res) => {
  try {
    const { name, email, department, role } = req.body;
    const username = name.toLowerCase().replace(/\s+/g, '.');
    const employee = {
      id: uuidv4(),
      name,
      email,
      department,
      role,
      username,
      processed: false,
      created_at: new Date().toISOString()
    };
    const params = { TableName: TABLE_NAME, Item: employee };
    await dynamodb.put(params).promise();
    res.status(201).json(employee);
  } catch (error) {
    console.error('Error:', error);
    res.status(500).json({ error: 'Failed to create employee' });
  }
});

app.delete('/api/employees/:id', async (req, res) => {
  try {
    const params = { TableName: TABLE_NAME, Key: { id: req.params.id } };
    await dynamodb.delete(params).promise();
    res.json({ message: 'Employee deleted successfully' });
  } catch (error) {
    console.error('Error:', error);
    res.status(500).json({ error: 'Failed to delete employee' });
  }
});

app.listen(PORT, '0.0.0.0', () => {
  console.log('HR Portal running on port ' + PORT);
  console.log('DynamoDB Table: ' + TABLE_NAME);
});
ENDOFSERVER

# Create public directory and HTML (keeping it simple)
mkdir -p public

# Download the HTML file content (avoiding quote issues)
cat > public/index.html << 'HTMLEND'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Innovatech HR Portal</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; }
        .header { background: #2563eb; color: white; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .container { max-width: 1400px; margin: 0 auto; padding: 30px 20px; }
        .title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        h1 { font-size: 28px; color: #1f2937; }
        .btn { background: #16a34a; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; }
        .btn:hover { background: #15803d; }
        .btn-danger { background: #dc2626; padding: 8px 16px; font-size: 12px; }
        .table-container { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
        table { width: 100%; border-collapse: collapse; }
        thead { background: #f9fafb; }
        th { padding: 16px; text-align: left; font-weight: 600; color: #374151; border-bottom: 2px solid #e5e7eb; }
        td { padding: 16px; border-bottom: 1px solid #e5e7eb; color: #4b5563; }
        tr:hover { background: #f9fafb; }
        .status { display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .status-pending { background: #fef3c7; color: #92400e; }
        .status-active { background: #d1fae5; color: #065f46; }
        .empty-state { text-align: center; padding: 60px 20px; color: #6b7280; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; }
        .modal.active { display: flex; }
        .modal-content { background: white; padding: 30px; border-radius: 12px; max-width: 500px; width: 90%; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 6px; font-weight: 600; color: #374151; font-size: 14px; }
        input { width: 100%; padding: 10px 12px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; }
        .form-actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }
        .btn-secondary { background: #6b7280; }
    </style>
</head>
<body>
    <div class="header"><div class="container"><h1 style="color: white; margin: 0;">Innovatech HR Portal</h1></div></div>
    <div class="container">
        <div class="title"><h1>Employee Management</h1><button class="btn" onclick="openModal()">Add New Employee</button></div>
        <div class="table-container"><table><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Department</th><th>Role</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead><tbody id="employeeTable"><tr><td colspan="8" class="empty-state">No employees found. Add your first employee!</td></tr></tbody></table></div>
    </div>
    <div id="employeeModal" class="modal"><div class="modal-content"><h2>Add New Employee</h2><form id="employeeForm"><div class="form-group"><label>Full Name *</label><input type="text" id="name" required></div><div class="form-group"><label>Email *</label><input type="email" id="email" required></div><div class="form-group"><label>Department *</label><input type="text" id="department" required></div><div class="form-group"><label>Role *</label><input type="text" id="role" required></div><div class="form-actions"><button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button><button type="submit" class="btn">Add Employee</button></div></form></div></div>
    <script>
        function openModal() { document.getElementById('employeeModal').classList.add('active'); }
        function closeModal() { document.getElementById('employeeModal').classList.remove('active'); document.getElementById('employeeForm').reset(); }
        async function loadEmployees() {
            try {
                const response = await fetch('/api/employees');
                const employees = await response.json();
                const tbody = document.getElementById('employeeTable');
                if (employees.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No employees found!</td></tr>';
                    return;
                }
                tbody.innerHTML = employees.map(emp => '<tr><td>' + emp.id.substring(0, 8) + '...</td><td>' + emp.name + '</td><td>' + emp.email + '</td><td>' + emp.department + '</td><td>' + emp.role + '</td><td><span class="status ' + (emp.processed ? 'status-active' : 'status-pending') + '">' + (emp.processed ? 'Active' : 'Pending') + '</span></td><td>' + new Date(emp.created_at).toLocaleDateString() + '</td><td><button class="btn btn-danger" onclick="deleteEmployee(\'' + emp.id + '\')">Delete</button></td></tr>').join('');
            } catch (error) { console.error('Error:', error); }
        }
        async function deleteEmployee(id) {
            if (!confirm('Delete this employee?')) return;
            try { await fetch('/api/employees/' + id, { method: 'DELETE' }); loadEmployees(); } catch (error) { alert('Failed to delete'); }
        }
        document.getElementById('employeeForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const employee = { name: document.getElementById('name').value, email: document.getElementById('email').value, department: document.getElementById('department').value, role: document.getElementById('role').value };
            try { await fetch('/api/employees', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(employee) }); closeModal(); loadEmployees(); } catch (error) { alert('Failed to add employee'); }
        });
        loadEmployees();
        setInterval(loadEmployees, 10000);
    </script>
</body>
</html>
HTMLEND

# Create Dockerfile
cat > Dockerfile << 'DOCKEREND'
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --production
COPY . .
EXPOSE 3000
CMD ["node", "server.js"]
DOCKEREND

# Build and run
docker build -t hr-portal:latest .
docker run -d --name hr-portal --restart unless-stopped -p 3000:3000 -e DYNAMODB_TABLE=$DYNAMODB_TABLE -e AWS_REGION=$AWS_REGION -e ADMIN_USERNAME=$ADMIN_USERNAME -e ADMIN_PASSWORD=$ADMIN_PASSWORD hr-portal:latest

echo "HR Portal setup completed" > /var/log/hr-portal-setup.log