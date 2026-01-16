from flask import Flask, request, jsonify, Response
import boto3
import os
import uuid
import datetime
from functools import wraps

app = Flask(__name__, static_folder='public', static_url_path='')

# AWS Configuration
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'eu-central-1'))
table = dynamodb.Table(os.environ.get('DYNAMODB_TABLE', 'cs3-nca-employees'))

# Admin Credentials
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Student123')

# Basic Auth Decorator
def check_auth(username, password):
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                'Authentication required', 401,
                {'WWW-Authenticate': 'Basic realm="HR Portal"'}
            )
        return f(*args, **kwargs)
    return decorated

# Health Check
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.datetime.utcnow().isoformat()})

# Serve Frontend
@app.route('/')
def index():
    return app.send_static_file('index.html')

# API: Get All Employees
@app.route('/api/employees', methods=['GET'])
@requires_auth
def get_employees():
    try:
        response = table.scan()
        return jsonify(response.get('Items', []))
    except Exception as e:
        print(f"Error fetching employees: {str(e)}")
        return jsonify({'error': 'Failed to fetch employees'}), 500

# API: Add Employee
@app.route('/api/employees', methods=['POST'])
@requires_auth
def create_employee():
    try:
        data = request.json
        name = data.get('name')
        
        employee = {
            'id': str(uuid.uuid4()),
            'name': name,
            'email': data.get('email'),
            'department': data.get('department'),
            'role': data.get('role'),
            'username': name.lower().replace(' ', '.'),
            'processed': False,
            'created_at': datetime.datetime.utcnow().isoformat()
        }
        
        table.put_item(Item=employee)
        print(f"Created employee: {employee['username']}")
        return jsonify(employee), 201
        
    except Exception as e:
        print(f"Error creating employee: {str(e)}")
        return jsonify({'error': 'Failed to create employee'}), 500

# API: Delete Employee
@app.route('/api/employees/<emp_id>', methods=['DELETE'])
@requires_auth
def delete_employee(emp_id):
    try:
        table.delete_item(Key={'id': emp_id})
        return jsonify({'message': 'Employee deleted successfully'})
    except Exception as e:
        print(f"Error deleting employee: {str(e)}")
        return jsonify({'error': 'Failed to delete employee'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)

    