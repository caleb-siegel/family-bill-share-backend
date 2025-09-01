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
            SELECT id, name, number, created_at, updated_at
            FROM group_bill_automation.bill_automator_lines 
            WHERE user_id = %s 
            ORDER BY number
        """, (request.user_id,))
        
        lines = []
        for line in cur.fetchall():
            lines.append({
                "id": line[0],
                "line_name": line[1],
                "line_number": line[2],
                "created_at": line[3].isoformat() if line[3] else None,
                "updated_at": line[4].isoformat() if line[4] else None
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
            (user_id, name, number, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            RETURNING id, name, number, created_at, updated_at
        """, (request.user_id, data['line_name'], data['line_number']))
        
        line_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Line created successfully",
            "line": {
                "id": line_data[0],
                "line_name": line_data[1],
                "line_number": line_data[2],
                "created_at": line_data[3].isoformat() if line_data[3] else None,
                "updated_at": line_data[4].isoformat() if line_data[4] else None
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
            SET name = %s, number = %s, updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING id, name, number, created_at, updated_at
        """, (data['line_name'], data['line_number'], line_id, request.user_id))
        
        line_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Line updated successfully",
            "line": {
                "id": line_data[0],
                "line_name": line_data[1],
                "line_number": line_data[2],
                "created_at": line_data[3].isoformat() if line_data[3] else None,
                "updated_at": line_data[4].isoformat() if line_data[4] else None
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
            SELECT fm.id, fm.family_id, fm.line_id, f.family, l.name, l.number
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
                "family": mapping[3],
                "line_name": mapping[4],
                "line_number": mapping[5]
            })
        
        cur.close()
        conn.close()
        
        return jsonify({"family_mappings": mappings})
        
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
