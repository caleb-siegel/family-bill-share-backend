"""
Simple Flask API for Verizon Family Plan Bill Automation.
Connects directly to Supabase without ORM complexity.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import psycopg2
import bcrypt
import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')

# Configure CORS
CORS(app, 
     origins=["https://family-bill-share.vercel.app", "http://localhost:5173", "http://localhost:3000"],
     supports_credentials=True,
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"])

# Add CORS headers to all responses
@app.after_request
def after_request(response):
    """Add CORS headers to all responses."""
    origin = request.headers.get('Origin')
    if origin in ["https://family-bill-share.vercel.app", "http://localhost:5173", "http://localhost:3000"]:
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# Database connection function
def get_db_connection():
    """Get a connection to the Supabase database."""
    try:
        conn = psycopg2.connect(os.getenv('SQLALCHEMY_DATABASE_URI'))
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

# Helper function to hash passwords
def hash_password(password):
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# Helper function to check passwords
def check_password(password, hashed):
    """Check if a password matches the hash."""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

# JWT helper functions
def create_jwt_token(user_id, email):
    """Create a JWT token for the user."""
    payload = {
        'user_id': user_id,
        'email': email,
        'exp': datetime.utcnow() + timedelta(days=7),  # Token expires in 7 days
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, os.getenv('SECRET_KEY', 'your-secret-key-change-in-production'), algorithm='HS256')

def decode_jwt_token(token):
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, os.getenv('SECRET_KEY', 'your-secret-key-change-in-production'), algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def require_auth(f):
    """Decorator to require JWT authentication."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid authorization header"}), 401
        
        token = auth_header.split(' ')[1]
        payload = decode_jwt_token(token)
        
        if not payload:
            return jsonify({"error": "Invalid or expired token"}), 401
        
        # Add user info to request
        request.user_id = payload['user_id']
        request.user_email = payload['email']
        
        return f(*args, **kwargs)
    return decorated_function

# Preflight handler for OPTIONS requests
@app.route('/api/<path:path>', methods=['OPTIONS'])
def handle_preflight(path):
    """Handle preflight OPTIONS requests for CORS."""
    response = jsonify({"message": "Preflight request handled"})
    response.headers.add('Access-Control-Allow-Origin', 'https://family-bill-share.vercel.app')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# API Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "message": "API is running"})

@app.route('/api/auth/signin', methods=['POST'])
def signin():
    """Authenticate an existing user."""
    try:
        data = request.get_json()
        if not data or 'email' not in data or 'password' not in data:
            return jsonify({"error": "Missing required fields: email, password"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Get user by email
        cur.execute("""
            SELECT id, name, email, password, created_at, updated_at 
            FROM group_bill_automation.bill_automator_users 
            WHERE email = %s
        """, (data['email'],))
        
        user_data = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user_data:
            return jsonify({"error": "Invalid email or password"}), 401
        
        # Check password
        if not check_password(data['password'], user_data[3]):
            return jsonify({"error": "Invalid email or password"}), 401
        
        # Create JWT token
        token = create_jwt_token(user_data[0], user_data[2])
        
        return jsonify({
            "message": "Sign in successful",
            "token": token,
            "user": {
                "id": user_data[0],
                "name": user_data[1],
                "email": user_data[2],
                "created_at": user_data[4].isoformat() if user_data[4] else None,
                "updated_at": user_data[5].isoformat() if user_data[5] else None
            }
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    """Create a new user account."""
    try:
        data = request.get_json()
        if not data or 'name' not in data or 'email' not in data or 'password' not in data:
            return jsonify({"error": "Missing required fields: name, email, password"}), 400
        
        # Check if user already exists
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if email already exists
        cur.execute("SELECT id FROM group_bill_automation.bill_automator_users WHERE email = %s", (data['email'],))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "User with this email already exists"}), 409
        
        # Hash the password
        hashed_password = hash_password(data['password'])
        
        # Create the user
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_users (name, email, password, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            RETURNING id, name, email, created_at
        """, (data['name'], data['email'], hashed_password))
        
        user_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        # Create JWT token
        token = create_jwt_token(user_data[0], user_data[2])
        
        return jsonify({
            "message": "User created successfully",
            "token": token,
            "user": {
                "id": user_data[0],
                "name": user_data[1],
                "email": user_data[2],
                "created_at": user_data[3].isoformat() if user_data[3] else None
            }
        }), 201
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/check', methods=['GET'])
@require_auth
def check_auth():
    """Check if user is authenticated and return basic user info."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, email 
            FROM group_bill_automation.bill_automator_users 
            WHERE id = %s
        """, (request.user_id,))
        
        user_data = cur.fetchone()
        
        if not user_data:
            cur.close()
            conn.close()
            return jsonify({"authenticated": False}), 401
        
        cur.close()
        conn.close()
        
        return jsonify({
            "authenticated": True,
            "user": {
                "id": user_data[0],
                "name": user_data[1],
                "email": user_data[2]
            },
            "is_configured": False  # Simplified for now
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Vercel serverless function entry point
def handler(request, context):
    """Vercel serverless function handler."""
    # Set CORS headers for preflight requests
    if request.method == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': 'https://family-bill-share.vercel.app',
                'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
                'Access-Control-Allow-Credentials': 'true'
            },
            'body': ''
        }
    
    # Handle the request using Flask
    with app.test_request_context(
        path=request.path,
        method=request.method,
        headers=request.headers,
        data=request.body if request.method in ['POST', 'PUT'] else None
    ):
        response = app.full_dispatch_request()
        
        # Add CORS headers to response
        headers = dict(response.headers)
        headers['Access-Control-Allow-Origin'] = 'https://family-bill-share.vercel.app'
        headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        headers['Access-Control-Allow-Credentials'] = 'true'
        
        return {
            'statusCode': response.status_code,
            'headers': headers,
            'body': response.get_data(as_text=True)
        }

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
