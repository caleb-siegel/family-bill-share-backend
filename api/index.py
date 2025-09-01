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
from parse_verizon import extract_charges_from_pdf

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')

# Configure CORS with more explicit settings
CORS(app, 
     origins=["https://family-bill-share.vercel.app", "http://localhost:5173", "http://localhost:3000"],
     supports_credentials=True,
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     expose_headers=["Content-Type", "Authorization"])

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

# Helper function to get user profile data
def get_user_profile(user_id):
    """Get complete user profile including all related data."""
    try:
        conn = get_db_connection()
        if not conn:
            return None
        
        cur = conn.cursor()
        
        # Get user basic info
        cur.execute("""
            SELECT id, name, email, created_at, updated_at 
            FROM group_bill_automation.bill_automator_users 
            WHERE id = %s
        """, (user_id,))
        
        user_data = cur.fetchone()
        if not user_data:
            cur.close()
            conn.close()
            return None
        
        user = {
            "id": user_data[0],
            "name": user_data[1],
            "email": user_data[2],
            "created_at": user_data[3].isoformat() if user_data[3] else None,
            "updated_at": user_data[4].isoformat() if user_data[4] else None
        }
        
        # Get user's families
        cur.execute("""
            SELECT id, family 
            FROM group_bill_automation.bill_automator_families 
            WHERE user_id = %s 
            ORDER BY id
        """, (user_id,))
        
        families = []
        for family in cur.fetchall():
            family_data = {
                "id": family[0],
                "family": family[1]
            }
            
            # Get family mappings (line names) for each family
            cur.execute("""
                SELECT id, line_id 
                FROM group_bill_automation.bill_automator_family_mapping 
                WHERE family_id = %s 
                ORDER BY id
            """, (family[0],))
            
            family_data["line_mappings"] = [
                {"id": mapping[0], "line_id": mapping[1]} 
                for mapping in cur.fetchall()
            ]
            
            families.append(family_data)
        
        # Get user's emails
        cur.execute("""
            SELECT id, emails 
            FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (user_id,))
        
        email_data = cur.fetchone()
        emails = email_data[1] if email_data else []
        
        # Get user's line adjustments
        cur.execute("""
            SELECT id, transfer_amount, line_to_add_to, line_to_remove_from 
            FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment 
            WHERE user_id = %s 
            ORDER BY id
        """, (user_id,))
        
        line_adjustments = [
            {
                "id": adj[0],
                "transfer_amount": float(adj[1]) if adj[1] else 0,
                "line_to_add_to": adj[2],
                "line_to_remove_from": adj[3]
            }
            for adj in cur.fetchall()
        ]
        
        # Get user's account reconciliation settings
        cur.execute("""
            SELECT id, reconciliation 
            FROM group_bill_automation.bill_automator_accountwide_reconciliation 
            WHERE user_id = %s
        """, (user_id,))
        
        reconciliation_data = cur.fetchone()
        reconciliation = reconciliation_data[1] if reconciliation_data else None
        
        cur.close()
        conn.close()
        
        return {
            "user": user,
            "families": families,
            "emails": emails,
            "line_adjustments": line_adjustments,
            "reconciliation": reconciliation,
            "is_configured": len(families) > 0 and len(emails) > 0
        }
        
    except Exception as e:
        print(f"Error getting user profile: {e}")
        return None

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
        
        # Get user data
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
        
        # Get user's families
        cur.execute("""
            SELECT id, family 
            FROM group_bill_automation.bill_automator_families 
            WHERE user_id = %s 
            ORDER BY id
        """, (request.user_id,))
        
        families = []
        for family in cur.fetchall():
            family_data = {
                "id": family[0],
                "family": family[1],
                "line_mappings": []
            }
            
            # Get family mappings (line names) for each family
            cur.execute("""
                SELECT id, line_id 
                FROM group_bill_automation.bill_automator_family_mapping 
                WHERE family_id = %s 
                ORDER BY id
            """, (family[0],))
            
            family_data["line_mappings"] = [
                {"id": mapping[0], "line_id": mapping[1]} 
                for mapping in cur.fetchall()
            ]
            
            families.append(family_data)
        
        # Get user's emails
        cur.execute("""
            SELECT emails 
            FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (request.user_id,))
        
        email_data = cur.fetchone()
        emails = email_data[0] if email_data else []
        
        # Get user's line adjustments
        cur.execute("""
            SELECT id, transfer_amount, line_to_remove_from, line_to_add_to 
            FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment 
            WHERE user_id = %s 
            ORDER BY id
        """, (request.user_id,))
        
        line_adjustments = [
            {
                "id": adj[0],
                "transfer_amount": float(adj[1]) if adj[1] else 0,
                "line_to_remove_from": adj[2],
                "line_to_add_to": adj[3]
            }
            for adj in cur.fetchall()
        ]
        
        # Get user's account reconciliation settings
        cur.execute("""
            SELECT reconciliation 
            FROM group_bill_automation.bill_automator_accountwide_reconciliation 
            WHERE user_id = %s
        """, (request.user_id,))
        
        reconciliation_data = cur.fetchone()
        reconciliation = reconciliation_data[0] if reconciliation_data else None
        
        cur.close()
        conn.close()
        
        # User is configured if they have at least one family and one email
        is_configured = len(families) > 0 and len(emails) > 0
        
        # Ensure all arrays are always arrays (defensive programming)
        families = families if families else []
        emails = emails if emails else []
        line_adjustments = line_adjustments if line_adjustments else []
        
        # Create the full profile that the frontend expects
        profile = {
            "user": {
                "id": user_data[0],
                "name": user_data[1],
                "email": user_data[2]
            },
            "families": families,
            "emails": emails,
            "line_adjustments": line_adjustments,
            "reconciliation": reconciliation,
            "is_configured": is_configured
        }
        
        return jsonify({
            "authenticated": True,
            "user": {
                "id": user_data[0],
                "name": user_data[1],
                "email": user_data[2]
            },
            "is_configured": is_configured,
            "profile": profile
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/profile', methods=['GET'])
@require_auth
def get_profile():
    """Get the current user's complete profile."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Get user data
        cur.execute("""
            SELECT id, name, email 
            FROM group_bill_automation.bill_automator_users 
            WHERE id = %s
        """, (request.user_id,))
        
        user_data = cur.fetchone()
        
        if not user_data:
            cur.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404
        
        # Get user's families
        cur.execute("""
            SELECT id, family 
            FROM group_bill_automation.bill_automator_families 
            WHERE user_id = %s 
            ORDER BY id
        """, (request.user_id,))
        
        families = []
        for family in cur.fetchall():
            family_data = {
                "id": family[0],
                "family": family[1],
                "line_mappings": []
            }
            
            # Get family mappings (line names) for each family
            cur.execute("""
                SELECT id, line_id 
                FROM group_bill_automation.bill_automator_family_mapping 
                WHERE family_id = %s 
                ORDER BY id
            """, (family[0],))
            
            family_data["line_mappings"] = [
                {"id": mapping[0], "line_id": mapping[1]} 
                for mapping in cur.fetchall()
            ]
            
            families.append(family_data)
        
        # Get user's emails
        cur.execute("""
            SELECT emails 
            FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (request.user_id,))
        
        email_data = cur.fetchone()
        emails = email_data[0] if email_data else []
        
        # Get user's line adjustments
        cur.execute("""
            SELECT id, transfer_amount, line_to_remove_from, line_to_add_to 
            FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment 
            WHERE user_id = %s 
            ORDER BY id
        """, (request.user_id,))
        
        line_adjustments = [
            {
                "id": adj[0],
                "transfer_amount": float(adj[1]) if adj[1] else 0,
                "line_to_remove_from": adj[2],
                "line_to_add_to": adj[3]
            }
            for adj in cur.fetchall()
        ]
        
        # Get user's account reconciliation settings
        cur.execute("""
            SELECT reconciliation 
            FROM group_bill_automation.bill_automator_accountwide_reconciliation 
            WHERE user_id = %s
        """, (request.user_id,))
        
        reconciliation_data = cur.fetchone()
        reconciliation = reconciliation_data[0] if reconciliation_data else None
        
        cur.close()
        conn.close()
        
        # User is configured if they have at least one family and one email
        is_configured = len(families) > 0 and len(emails) > 0
        
        # Ensure all arrays are always arrays (defensive programming)
        families = families if families else []
        emails = emails if emails else []
        line_adjustments = line_adjustments if line_adjustments else []
        
        return jsonify({
            "user": {
                "id": user_data[0],
                "name": user_data[1],
                "email": user_data[2]
            },
            "families": families,
            "emails": emails,
            "line_adjustments": line_adjustments,
            "reconciliation": reconciliation,
            "is_configured": is_configured
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/signout', methods=['POST'])
@require_auth
def signout():
    """Sign out the current user."""
    # With JWT, we don't need to clear anything server-side
    # The client should discard the token
    return jsonify({"message": "Signed out successfully"})

@app.route('/api/lines', methods=['GET'])
@require_auth
def get_lines():
    """Get all lines for the current user."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Get user's lines
        cur.execute("""
            SELECT id, name, number, device, created_at, updated_at
            FROM group_bill_automation.bill_automator_lines 
            WHERE user_id = %s 
            ORDER BY number
        """, (request.user_id,))
        
        lines = []
        for line in cur.fetchall():
            lines.append({
                "id": line[0],
                "name": line[1],
                "number": line[2],
                "device": line[3],
                "created_at": line[4].isoformat() if line[4] else None,
                "updated_at": line[5].isoformat() if line[5] else None
            })
        
        cur.close()
        conn.close()
        
        return jsonify({"lines": lines})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/lines', methods=['POST'])
@require_auth
def create_line():
    """Create a new line for the current user."""
    try:
        data = request.get_json()
        if not data or 'line_name' not in data or 'line_number' not in data:
            return jsonify({"error": "Missing required fields: line_name, line_number"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if line number already exists for this user
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_lines 
            WHERE user_id = %s AND number = %s
        """, (request.user_id, data['line_number']))
        
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Line number already exists for this user"}), 409
        
        # Create the line
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_lines 
            (user_id, name, number, device, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            RETURNING id, name, number, device, created_at, updated_at
        """, (request.user_id, data['line_name'], data['line_number'], data.get('device', '')))
        
        line_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Line created successfully",
            "line": {
                "id": line_data[0],
                "name": line_data[1],
                "number": line_data[2],
                "device": line_data[3],
                "created_at": line_data[4].isoformat() if line_data[4] else None,
                "updated_at": line_data[5].isoformat() if line_data[5] else None
            }
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/lines/<int:line_id>', methods=['PUT'])
@require_auth
def update_line(line_id):
    """Update an existing line."""
    try:
        data = request.get_json()
        if not data or 'line_name' not in data or 'line_number' not in data:
            return jsonify({"error": "Missing required fields: line_name, line_number"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if line belongs to user
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_lines 
            WHERE id = %s AND user_id = %s
        """, (line_id, request.user_id))
        
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Line not found"}), 404
        
        # Check if new line number conflicts with existing line
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_lines 
            WHERE user_id = %s AND number = %s AND id != %s
        """, (request.user_id, data['line_number'], line_id))
        
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Line number already exists for this user"}), 409
        
        # Update the line
        cur.execute("""
            UPDATE group_bill_automation.bill_automator_lines 
            SET name = %s, number = %s, device = %s, updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING id, name, number, device, created_at, updated_at
        """, (data['line_name'], data['line_number'], data.get('device', ''), line_id, request.user_id))
        
        line_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Line updated successfully",
            "line": {
                "id": line_data[0],
                "name": line_data[1],
                "number": line_data[2],
                "device": line_data[3],
                "created_at": line_data[4].isoformat() if line_data[4] else None,
                "updated_at": line_data[5].isoformat() if line_data[5] else None
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/lines/<int:line_id>', methods=['DELETE'])
@require_auth
def delete_line(line_id):
    """Delete a line."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if line belongs to user
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_lines 
            WHERE id = %s AND user_id = %s
        """, (line_id, request.user_id))
        
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Line not found"}), 404
        
        # Delete the line
        cur.execute("""
            DELETE FROM group_bill_automation.bill_automator_lines 
            WHERE id = %s AND user_id = %s
        """, (line_id, request.user_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({"message": "Line deleted successfully"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/family-mappings', methods=['GET'])
@require_auth
def get_family_mappings():
    """Get all family mappings for the current user."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Get user's family mappings with family and line information
        cur.execute("""
            SELECT fm.id, fm.family_id, fm.line_id, f.family, l.name, l.number, l.device
            FROM group_bill_automation.bill_automator_family_mapping fm
            JOIN group_bill_automation.bill_automator_families f ON fm.family_id = f.id
            JOIN group_bill_automation.bill_automator_lines l ON fm.line_id = l.id
            WHERE f.user_id = %s
            ORDER BY f.family, l.number
        """, (request.user_id,))
        
        mappings = []
        for mapping in cur.fetchall():
            mappings.append({
                "id": mapping[0],
                "family_id": mapping[1],
                "line_id": mapping[2],
                "family_name": mapping[3],
                "line_name": mapping[4],
                "line_number": mapping[5],
                "line_device": mapping[6]
            })
        
        cur.close()
        conn.close()
        
        return jsonify({"mappings": mappings})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/family-mappings', methods=['POST'])
@require_auth
def create_family_mapping():
    """Create a new family mapping."""
    try:
        data = request.get_json()
        if not data or 'family_id' not in data or 'line_id' not in data:
            return jsonify({"error": "Missing required fields: family_id, line_id"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if family belongs to user
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_families 
            WHERE id = %s AND user_id = %s
        """, (data['family_id'], request.user_id))
        
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Family not found"}), 404
        
        # Check if line belongs to user
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_lines 
            WHERE id = %s AND user_id = %s
        """, (data['line_id'], request.user_id))
        
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Line not found"}), 404
        
        # Check if mapping already exists
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_family_mapping 
            WHERE family_id = %s AND line_id = %s
        """, (data['family_id'], data['line_id']))
        
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Family mapping already exists"}), 409
        
        # Create the mapping
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_family_mapping 
            (family_id, line_id)
            VALUES (%s, %s)
            RETURNING id, family_id, line_id
        """, (data['family_id'], data['line_id']))
        
        mapping_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Family mapping created successfully",
            "family_mapping": {
                "id": mapping_data[0],
                "family_id": mapping_data[1],
                "line_id": mapping_data[2]
            }
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/family-mappings/<int:mapping_id>', methods=['DELETE'])
@require_auth
def delete_family_mapping(mapping_id):
    """Delete a family mapping."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if mapping belongs to user's family
        cur.execute("""
            SELECT fm.id FROM group_bill_automation.bill_automator_family_mapping fm
            JOIN group_bill_automation.bill_automator_families f ON fm.family_id = f.id
            WHERE fm.id = %s AND f.user_id = %s
        """, (mapping_id, request.user_id))
        
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Family mapping not found"}), 404
        
        # Delete the mapping
        cur.execute("""
            DELETE FROM group_bill_automation.bill_automator_family_mapping 
            WHERE id = %s
        """, (mapping_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({"message": "Family mapping deleted successfully"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/accountwide-reconciliation', methods=['GET'])
@require_auth
def get_accountwide_reconciliation():
    """Get account-wide reconciliation for the current user."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT reconciliation 
            FROM group_bill_automation.bill_automator_accountwide_reconciliation 
            WHERE user_id = %s
        """, (request.user_id,))
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            return jsonify({
                "success": True,
                "reconciliation": result[0]
            })
        else:
            return jsonify({
                "success": False,
                "reconciliation": None
            })
    
    except Exception as e:
        print(f"Error getting account-wide reconciliation: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/accountwide-reconciliation', methods=['POST'])
@require_auth
def save_accountwide_reconciliation():
    """Save account-wide reconciliation settings for the current user."""
    try:
        data = request.get_json()
        if not data or 'reconciliation' not in data:
            return jsonify({"error": "Missing required field: reconciliation"}), 400
        
        reconciliation = data['reconciliation']
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Delete any existing reconciliation for this user
        cur.execute("""
            DELETE FROM group_bill_automation.bill_automator_accountwide_reconciliation 
            WHERE user_id = %s
        """, (request.user_id,))
        
        # Insert new reconciliation
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_accountwide_reconciliation 
            (user_id, reconciliation) 
            VALUES (%s, %s)
            RETURNING id
        """, (request.user_id, reconciliation))
        
        reconciliation_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "Account-wide reconciliation saved successfully",
            "reconciliation_id": reconciliation_id
        })
    
    except Exception as e:
        print(f"Error saving account-wide reconciliation: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/line-discount-transfer', methods=['GET'])
@require_auth
def get_line_discount_transfer():
    """Get line discount transfer for the current user."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT transfer_amount, line_to_remove_from, line_to_add_to
            FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment 
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (request.user_id,))
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            return jsonify({
                "success": True,
                "transfer": {
                    "transfer_amount": result[0],
                    "line_to_remove_from": result[1],
                    "line_to_add_to": result[2]
                }
            })
        else:
            return jsonify({
                "success": False,
                "transfer": None
            })
    
    except Exception as e:
        print(f"Error getting line discount transfer: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/line-discount-transfer', methods=['POST'])
@require_auth
def save_line_discount_transfer():
    """Save line discount transfer adjustment for the current user."""
    try:
        data = request.get_json()
        if not data or 'transfer_amount' not in data or 'line_to_remove_from' not in data or 'line_to_add_to' not in data:
            return jsonify({"error": "Missing required fields: transfer_amount, line_to_remove_from, line_to_add_to"}), 400
        
        transfer_amount = float(data['transfer_amount'])
        line_to_remove_from = int(data['line_to_remove_from'])
        line_to_add_to = int(data['line_to_add_to'])
        
        if transfer_amount <= 0:
            return jsonify({"error": "Transfer amount must be greater than 0"}), 400
        
        if line_to_remove_from == line_to_add_to:
            return jsonify({"error": "Cannot transfer to the same line"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Verify that both lines exist and belong to this user
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_lines 
            WHERE id IN (%s, %s) AND user_id = %s
        """, (line_to_remove_from, line_to_add_to, request.user_id))
        
        lines = cur.fetchall()
        if len(lines) != 2:
            return jsonify({"error": "One or both lines not found or do not belong to user"}), 400
        
        # Check if an existing transfer exists for this user with the same remove/add lines
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment 
            WHERE user_id = %s AND line_to_remove_from = %s AND line_to_add_to = %s
        """, (request.user_id, line_to_remove_from, line_to_add_to))
        
        existing_transfer = cur.fetchone()
        
        if existing_transfer:
            # Update existing transfer
            cur.execute("""
                UPDATE group_bill_automation.bill_automator_line_discount_transfer_adjustment 
                SET transfer_amount = %s, updated_at = NOW()
                WHERE id = %s
            """, (transfer_amount, existing_transfer[0]))
            
            transfer_id = existing_transfer[0]
            message = "Line discount transfer updated successfully"
        else:
            # Insert new transfer
            cur.execute("""
                INSERT INTO group_bill_automation.bill_automator_line_discount_transfer_adjustment 
                (user_id, transfer_amount, line_to_remove_from, line_to_add_to) 
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (request.user_id, transfer_amount, line_to_remove_from, line_to_add_to))
            
            transfer_id = cur.fetchone()[0]
            message = "Line discount transfer saved successfully"
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": message,
            "transfer_id": transfer_id
        })
    
    except ValueError:
        return jsonify({"error": "Invalid transfer amount"}), 400
    except Exception as e:
        print(f"Error saving line discount transfer: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/parse-pdf', methods=['POST'])
@require_auth
def parse_pdf():
    """Parse a PDF bill and extract line details."""
    print("=== PARSE PDF ENDPOINT CALLED ===")
    try:
        # Get the PDF file from the request
        if 'pdf' not in request.files:
            print("ERROR: No PDF file in request.files")
            return jsonify({"error": "No PDF file provided"}), 400
        
        pdf_file = request.files['pdf']
        print(f"PDF file received: {pdf_file.filename}")
        
        if pdf_file.filename == '':
            print("ERROR: Empty filename")
            return jsonify({"error": "No PDF file selected"}), 400
        
        # Read the PDF file into bytes
        pdf_bytes = pdf_file.read()
        print(f"PDF bytes read: {len(pdf_bytes)} bytes")
        
        try:
            print("Attempting to import parse_verizon...")
            # Import parse_verizon functions
            import parse_verizon
            print("parse_verizon imported successfully")
            
            print("Attempting to import fitz...")
            import fitz
            print("fitz imported successfully")
            
            print("Calling extract_charges_from_pdf...")
            # Extract charges using the same approach as parse_verizon.py
            account_wide_value, line_details = parse_verizon.extract_charges_from_pdf(pdf_bytes)
            print(f"PDF parsing completed. Account-wide value: {account_wide_value}, Line details count: {len(line_details)}")
            
            # Get existing lines from database for this user
            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "Database connection failed"}), 500
            
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, number, device
                FROM group_bill_automation.bill_automator_lines 
                WHERE user_id = %s
            """, (request.user_id,))
            
            existing_lines = {}
            for line in cur.fetchall():
                # Create a composite key using name and number only
                composite_key = f"{line[1]}|{line[2]}"  # name|number
                existing_lines[composite_key] = {
                    "id": line[0],
                    "name": line[1],
                    "number": line[2],
                    "device": line[3],
                    "exists": True
                }
            
            cur.close()
            conn.close()
            
            # Process parsed line details and check against existing lines
            parsed_lines = []
            
            for unique_key, line_detail in line_details.items():
                name = line_detail["name"]
                device = line_detail["device"]
                number = line_detail["number"]
                charge = line_detail["charge"]
                
                # Create composite key for this parsed line
                parsed_composite_key = f"{name}|{number}"
                
                exists = parsed_composite_key in existing_lines and number != 'Unknown'
                
                line_data = {
                    "unique_key": unique_key,
                    "name": name,
                    "number": number,
                    "device": device,
                    "charge": charge,
                    "exists": exists,
                    "selected": False  # User will select which lines to save
                }
                
                if line_data["exists"]:
                    # Reference existing line
                    existing_line = existing_lines[parsed_composite_key]
                    line_data["id"] = existing_line["id"]
                
                parsed_lines.append(line_data)
            
            return jsonify({
                "success": True,
                "lines": parsed_lines,
                "existing_lines_count": len([line for line in parsed_lines if line["exists"]]),
                "new_lines_count": len([line for line in parsed_lines if not line["exists"]]),
                "total_charge": sum(line["charge"] for line in parsed_lines),
                "account_wide_value": account_wide_value
            })
            
        except ImportError as e:
            print(f"IMPORT ERROR: {str(e)}")
            return jsonify({"error": f"Import error: {str(e)}"}), 500
        except Exception as e:
            print(f"PDF PARSING ERROR: {str(e)}")
            return jsonify({"error": f"Failed to parse PDF: {str(e)}"}), 500
    
    except Exception as e:
        print(f"GENERAL ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/families', methods=['POST'])
@require_auth
def create_families():
    """Create families for the authenticated user."""
    try:
        data = request.get_json()
        if not data or 'families' not in data or not isinstance(data['families'], list):
            return jsonify({"error": "Missing required field: families (must be an array)"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Delete existing families for this user
        cur.execute("""
            DELETE FROM group_bill_automation.bill_automator_families 
            WHERE user_id = %s
        """, (request.user_id,))
        
        # Insert new families
        family_ids = []
        for family_name in data['families']:
            cur.execute("""
                INSERT INTO group_bill_automation.bill_automator_families 
                (user_id, family, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                RETURNING id
            """, (request.user_id, family_name))
            family_ids.append(cur.fetchone()[0])
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "message": f"Families created successfully",
            "families": data['families'],
            "family_ids": family_ids
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/families', methods=['PUT'])
@require_auth
def update_families():
    """Update families for the authenticated user."""
    try:
        data = request.get_json()
        if not data or 'families' not in data or not isinstance(data['families'], list):
            return jsonify({"error": "Missing required field: families (must be an array)"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Delete existing families for this user
        cur.execute("""
            DELETE FROM group_bill_automation.bill_automator_families 
            WHERE user_id = %s
        """, (request.user_id,))
        
        # Insert new families
        family_ids = []
        for family_name in data['families']:
            cur.execute("""
                INSERT INTO group_bill_automation.bill_automator_families 
                (user_id, family, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                RETURNING id
            """, (request.user_id, family_name))
            family_ids.append(cur.fetchone()[0])
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "message": f"Families updated successfully",
            "families": data['families'],
            "family_ids": family_ids
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/families/add', methods=['POST'])
@require_auth
def add_family():
    """Add a single family for the authenticated user."""
    try:
        data = request.get_json()
        if not data or 'family' not in data:
            return jsonify({"error": "Missing required field: family"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Insert new family
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_families 
            (user_id, family, created_at, updated_at)
            VALUES (%s, %s, NOW(), NOW())
            RETURNING id, family
        """, (request.user_id, data['family']))
        
        family_data = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Family added successfully",
            "family": {
                "id": family_data[0],
                "family": family_data[1]
            }
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/emails', methods=['POST'])
@require_auth
def create_emails():
    """Create emails for the authenticated user."""
    try:
        data = request.get_json()
        if not data or 'emails' not in data or not isinstance(data['emails'], list):
            return jsonify({"error": "Missing required field: emails (must be an array)"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Delete existing emails for this user
        cur.execute("""
            DELETE FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (request.user_id,))
        
        # Insert new emails
        for email in data['emails']:
            cur.execute("""
                INSERT INTO group_bill_automation.bill_automator_emails 
                (user_id, emails, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
            """, (request.user_id, [email]))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "message": f"Emails created successfully",
            "emails": data['emails']
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/emails', methods=['PUT'])
@require_auth
def update_emails():
    """Update emails for the authenticated user."""
    try:
        data = request.get_json()
        if not data or 'emails' not in data or not isinstance(data['emails'], list):
            return jsonify({"error": "Missing required field: emails (must be an array)"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Delete existing emails for this user
        cur.execute("""
            DELETE FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (request.user_id,))
        
        # Insert new emails
        for email in data['emails']:
            cur.execute("""
                INSERT INTO group_bill_automation.bill_automator_emails 
                (user_id, emails, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
            """, (request.user_id, [email]))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "message": f"Emails updated successfully",
            "emails": data['emails']
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/emails/add', methods=['POST'])
@require_auth
def add_email():
    """Add a single email for the authenticated user."""
    try:
        data = request.get_json()
        if not data or 'email' not in data:
            return jsonify({"error": "Missing required field: email"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Insert new email
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_emails 
            (user_id, emails, created_at, updated_at)
            VALUES (%s, %s, NOW(), NOW())
            RETURNING id
        """, (request.user_id, [data['email']]))
        
        email_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Email added successfully",
            "email_id": email_id,
            "email": data['email']
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/save-selected-lines', methods=['POST'])
@require_auth
def save_selected_lines():
    """Save only the selected lines to the database."""
    
    try:
        data = request.get_json()
        if not data or 'lines' not in data or not isinstance(data['lines'], list):
            return jsonify({"error": "Missing required field: lines (must be an array)"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        saved_lines = []
        
        for line in data['lines']:
            if line.get('selected', False) and not line.get('exists', False):
                # Only save new lines that are selected
                cur.execute("""
                    INSERT INTO group_bill_automation.bill_automator_lines 
                    (user_id, name, number, device, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    RETURNING id
                """, (request.user_id, line['name'], line['number'], line['device']))
                
                line_id = cur.fetchone()[0]
                
                # If line has a family assigned, create the family mapping
                if line.get('family'):
                    family_id = line['family']
                    cur.execute("""
                        INSERT INTO group_bill_automation.bill_automator_family_mapping 
                        (family_id, line_id) 
                        VALUES (%s, %s)
                    """, (family_id, line_id))
                
                saved_lines.append({
                    **line,
                    "id": line_id,
                    "exists": True
                })
            elif line.get('exists', False):
                # Keep existing lines as they are
                saved_lines.append(line)
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Successfully saved {len(saved_lines)} lines",
            "saved_lines": saved_lines
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/send-bill-emails', methods=['POST'])
@require_auth
def send_bill_emails():
    """Send bill emails with family totals to configured email addresses."""
    
    try:
        data = request.get_json()
        if not data or 'family_totals' not in data:
            return jsonify({"error": "Missing required field: family_totals"}), 400
        
        family_totals = data['family_totals']
        if not isinstance(family_totals, list):
            return jsonify({"error": "family_totals must be a list"}), 400
        
        # Get user's email addresses
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Get user's email
        cur.execute("""
            SELECT email FROM group_bill_automation.bill_automator_users 
            WHERE id = %s
        """, (request.user_id,))
        
        user_email_record = cur.fetchone()
        if not user_email_record:
            cur.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404
        
        user_email = user_email_record[0]
        
        # Get user's email addresses
        cur.execute("""
            SELECT emails FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (request.user_id,))
        
        email_record = cur.fetchone()
        cur.close()
        conn.close()
        
        if not email_record or not email_record[0]:
            return jsonify({"error": "No email addresses configured for this user"}), 400
        
        email_list = email_record[0]
        
        # Convert family totals to the format expected by parse_verizon
        # The parse_verizon functions expect person_totals as a dict
        person_totals = {}
        for family_total in family_totals:
            if 'family' in family_total and 'total' in family_total:
                family_name = family_total['family']
                total_amount = float(family_total['total'])
                person_totals[family_name] = total_amount
        
        # Import parse_verizon functions
        import parse_verizon
        
        # Send the email using the existing functionality with user's email list
        parse_verizon.send_email(person_totals, email_list, user_email)
        
        return jsonify({
            "success": True,
            "message": f"Bill emails sent successfully to {len(email_list)} recipients",
            "emails_sent": len(email_list),
            "family_totals": family_totals
        })
    
    except Exception as e:
        print(f"Error sending bill emails: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/automated_process', methods=['POST'])
@require_auth
def automated_process():
    """Fully automated bill processing using saved configuration."""
    
    try:
        # Get the PDF file from the request
        if 'pdf' not in request.files:
            return jsonify({"error": "No PDF file provided"}), 400
        
        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({"error": "No PDF file selected"}), 400
        
        # Get user's complete configuration from database
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Get user's families and line mappings
        
        # Get user's families and line mappings
        cur.execute("""
            SELECT f.id, f.family, fm.line_id, l.name as line_name, l.number as line_number, l.device as line_device
            FROM group_bill_automation.bill_automator_families f
            LEFT JOIN group_bill_automation.bill_automator_family_mapping fm ON f.id = fm.family_id
            LEFT JOIN group_bill_automation.bill_automator_lines l ON fm.line_id = l.id
            WHERE f.user_id = %s
            ORDER BY f.id, fm.id
        """, (request.user_id,))
        
        family_mappings = cur.fetchall()
        

        
        # Get user's emails
        cur.execute("""
            SELECT emails FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (request.user_id,))
        
        email_record = cur.fetchone()
        if not email_record or not email_record[0]:
            return jsonify({
                "error": "No email addresses configured",
                "message": "Please configure email addresses before using automated processing"
            }), 400
        
        emails = email_record[0]  # This is already a list of email addresses
        
        # Get user's email for sender
        cur.execute("""
            SELECT email FROM group_bill_automation.bill_automator_users 
            WHERE id = %s
        """, (request.user_id,))
        
        user_email_record = cur.fetchone()
        if not user_email_record:
            cur.close()
            conn.close()
            return jsonify({"error": "User not found"}), 404
        
        user_email = user_email_record[0]
        
        # Get user's line adjustments (discount transfers)
        cur.execute("""
            SELECT transfer_amount, line_to_remove_from, line_to_add_to
            FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment 
            WHERE user_id = %s
        """, (request.user_id,))
        
        line_adjustments = cur.fetchall()
        
        # Get user's account-wide reconciliation
        cur.execute("""
            SELECT reconciliation
            FROM group_bill_automation.bill_automator_accountwide_reconciliation 
            WHERE user_id = %s
        """, (request.user_id,))
        
        reconciliation_record = cur.fetchone()
        account_wide_reconciliation = reconciliation_record[0] if reconciliation_record else None
        
        cur.close()
        conn.close()
        
        # Check if user has complete configuration
        if not family_mappings:
            return jsonify({
                "error": "Incomplete configuration",
                "message": "Please configure families and line mappings before using automated processing"
            }), 400
        
        # Step 1: Parse the PDF using the same approach as parse_verizon.py
        import tempfile
        import os
        
        # Read the PDF file into bytes (same as parse-pdf endpoint)
        pdf_bytes = pdf_file.read()
        
        try:
            # Import parse_verizon functions
            import parse_verizon
            
            # Extract charges using the same approach as parse_verizon.py
            account_wide_value, line_details = parse_verizon.extract_charges_from_pdf(pdf_bytes)
            
            # Step 2: Calculate family totals based on line mappings
            family_totals = {}
            
            # Group charges by family based on line mappings
            for family_id, family_name, line_id, line_name, line_number, line_device in family_mappings:
                if family_name not in family_totals:
                    family_totals[family_name] = 0
                
                # Find charges for this line by matching name and number
                for line_key, line_data in line_details.items():
                    pdf_name = line_data.get('name')
                    pdf_number = line_data.get('number')
                    pdf_charge = line_data.get('charge', 0)
                    
                    if (pdf_name == line_name and pdf_number == line_number):
                        family_totals[family_name] += pdf_charge
            
            # Step 3: Apply line adjustments (discount transfers)
            for transfer_amount, line_to_remove_from, line_to_add_to in line_adjustments:
                # Convert decimal to float for arithmetic operations
                transfer_amount_float = float(transfer_amount)
                
                # Find which family the lines belong to
                for family_id, family_name, line_id, line_name, line_number, line_device in family_mappings:
                    if line_id == line_to_remove_from:
                        family_totals[family_name] -= transfer_amount_float
                    elif line_id == line_to_add_to:
                        family_totals[family_name] += transfer_amount_float
            
            # Step 4: Apply account-wide reconciliation if configured
            if account_wide_reconciliation:
                if account_wide_reconciliation == "evenly":
                    # Distribute account-wide charges/credits equally among families
                    num_families = len(set(f[1] for f in family_mappings))  # unique family names
                    if num_families > 0:
                        per_family_share = account_wide_value / num_families
                        for family_name in family_totals:
                            family_totals[family_name] += per_family_share
                else:
                    # Try to parse as a numeric value
                    try:
                        account_wide_amount = float(account_wide_reconciliation)
                        # Distribute account-wide amount equally among families
                        num_families = len(set(f[1] for f in family_mappings))  # unique family names
                        if num_families > 0:
                            per_family_share = account_wide_amount / num_families
                            for family_name in family_totals:
                                family_totals[family_name] += per_family_share
                    except ValueError:
                        # If reconciliation is not a valid number, skip it
                        pass
            
            # Step 5: Send emails using the existing functionality
            try:
                # Convert family totals to the format expected by parse_verizon.send_email
                person_totals = family_totals  # The function can handle family names as person names
                
                # Send email using the existing functionality
                parse_verizon.send_email(person_totals, emails, user_email)
                
            except Exception as e:
                return jsonify({"error": f"Failed to send emails: {str(e)}"}), 500
            
            total_amount = sum(family_totals.values())
            
            return jsonify({
                "success": True,
                "message": "Bill processed and emails sent successfully",
                "family_totals": family_totals,
                "emails_sent": len(emails),
                "total_amount": total_amount,
                "account_wide_value": account_wide_value,
                "line_adjustments_applied": len(line_adjustments),
                "account_wide_reconciliation_applied": account_wide_reconciliation is not None
            })
            
        except Exception as e:
            raise e
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/onboarding/complete', methods=['POST'])
@require_auth
def complete_onboarding():
    """Mark user onboarding as complete and return updated profile."""
    
    try:
        # Get updated profile
        profile = get_user_profile(request.user_id)
        if not profile:
            return jsonify({"error": "User not found"}), 404
        
        return jsonify({
            "message": "Onboarding completed successfully",
            "profile": profile
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
