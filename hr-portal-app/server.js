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