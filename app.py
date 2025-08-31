"""
Simple Flask API for Verizon Family Plan Bill Automation.
Connects directly to Supabase without ORM complexity.
"""

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_session import Session
import os
import psycopg2
import bcrypt
from dotenv import load_dotenv
from services.pdf_service import PDFService
from parse_verizon import extract_charges_from_pdf

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

CORS(app, supports_credentials=True)

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
            SELECT id, transfer_amount, line_to_remove_from, line_to_add_to 
            FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment 
            WHERE user_id = %s 
            ORDER BY id
        """, (user_id,))
        
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

# API Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "message": "API is running"})

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """Simple test endpoint that doesn't require database."""
    return jsonify({
        "message": "Test endpoint working",
        "timestamp": "2025-01-15T18:30:00Z",
        "backend": "Flask",
        "port": 5002
    })

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
        
        # Set session
        session['user_id'] = user_data[0]
        session['user_email'] = user_data[2]
        
        return jsonify({
            "message": "User created successfully", 
            "user": {
                "id": user_data[0],
                "name": user_data[1],
                "email": user_data[2],
                "created_at": user_data[3].isoformat() if user_data[3] else None
            }
        }), 201
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        
        # Set session
        session['user_id'] = user_data[0]
        session['user_email'] = user_data[2]
        
        return jsonify({
            "message": "Sign in successful",
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

@app.route('/api/auth/profile', methods=['GET'])
def get_profile():
    """Get the current user's complete profile."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    profile = get_user_profile(session['user_id'])
    if not profile:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify(profile)

@app.route('/api/auth/signout', methods=['POST'])
def signout():
    """Sign out the current user."""
    session.clear()
    return jsonify({"message": "Signed out successfully"})

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    """Check if user is authenticated and return basic user info."""
    if 'user_id' not in session:
        return jsonify({"authenticated": False}), 401
    
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, email 
            FROM group_bill_automation.bill_automator_users 
            WHERE id = %s
        """, (session['user_id'],))
        
        user_data = cur.fetchone()
        
        if not user_data:
            cur.close()
            conn.close()
            session.clear()
            return jsonify({"authenticated": False}), 401
        
        # Get full user profile data
        profile = get_user_profile(session['user_id'])
        
        cur.close()
        conn.close()
        
        if profile:
            return jsonify({
                "authenticated": True,
                "user": {
                    "id": user_data[0],
                    "name": user_data[1],
                    "email": user_data[2]
                },
                "is_configured": profile["is_configured"],
                "profile": profile
            })
        else:
            # Fallback to basic data if profile loading fails
            return jsonify({
                "authenticated": True,
                "user": {
                    "id": user_data[0],
                    "name": user_data[1],
                    "email": user_data[2]
                },
                "is_configured": False
            })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all users from the database."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("SELECT id, name, email, created_at, updated_at FROM group_bill_automation.bill_automator_users ORDER BY id")
        users = cur.fetchall()
        
        user_list = []
        for user in users:
            user_list.append({
                "id": user[0],
                "name": user[1],
                "email": user[2],
                "created_at": user[3].isoformat() if user[3] else None,
                "updated_at": user[4].isoformat() if user[4] else None
            })
        
        cur.close()
        conn.close()
        
        return jsonify({"users": user_list})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/users', methods=['POST'])
def create_user():
    """Create a new user."""
    try:
        data = request.get_json()
        if not data or 'name' not in data or 'email' not in data or 'password' not in data:
            return jsonify({"error": "Missing required fields: name, email, password"}), 500
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_users (name, email, password, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (data['name'], data['email'], data['password']))
        
        user_id = cur.fetchone()[0]
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({"message": "User created successfully", "user_id": user_id}), 201
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/families', methods=['GET'])
def get_families():
    """Get all families for a user."""
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id parameter required"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT id, family FROM group_bill_automation.bill_automator_families 
            WHERE user_id = %s ORDER BY id
        """, (user_id,))
        families = cur.fetchall()
        
        family_list = []
        for family in families:
            family_list.append({
                "id": family[0],
                "family": family[1]
            })
        
        cur.close()
        conn.close()
        
        return jsonify({"families": family_list})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/families', methods=['POST'])
def create_families():
    """Create or update families for the authenticated user while preserving mappings."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        data = request.get_json()
        if not data or 'families' not in data or not isinstance(data['families'], list):
            return jsonify({"error": "Missing required field: families (must be an array)"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cur = conn.cursor()

        # Get existing families to preserve mappings
        cur.execute("""
            SELECT id, family
            FROM group_bill_automation.bill_automator_families
            WHERE user_id = %s
        """, (session['user_id'],))

        existing_families = {}
        for row in cur.fetchall():
            existing_families[row[1]] = row[0]  # family_name -> family_id

        print(f"POST /api/families - Existing families: {existing_families}")
        print(f"POST /api/families - New families: {data['families']}")

        families_data = []

        # Process each family
        for family_name in data['families']:
            if family_name in existing_families:
                # Family already exists, keep the existing ID
                family_id = existing_families[family_name]
                print(f"Preserving existing family: {family_name} (ID: {family_id})")
                families_data.append({
                    "id": family_id,
                    "family": family_name
                })
            else:
                # New family, insert it
                print(f"Creating new family: {family_name}")
                cur.execute("""
                    INSERT INTO group_bill_automation.bill_automator_families (user_id, family)
                    VALUES (%s, %s)
                    RETURNING id, family
                """, (session['user_id'], family_name))

                family_data = cur.fetchone()
                families_data.append({
                    "id": family_data[0],
                    "family": family_data[1]
                })

        # Remove families that are no longer in the list
        new_family_names = set(data['families'])
        for existing_family_name, existing_family_id in existing_families.items():
            if existing_family_name not in new_family_names:
                # Delete the family (this will cascade delete mappings due to foreign key)
                cur.execute("""
                    DELETE FROM group_bill_automation.bill_automator_families
                    WHERE id = %s
                """, (existing_family_id,))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "message": "Families saved successfully",
            "families": families_data
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/families', methods=['PUT'])
def update_families():
    """Update families for the authenticated user while preserving mappings."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        data = request.get_json()
        if not data or 'families' not in data or not isinstance(data['families'], list):
            return jsonify({"error": "Missing required field: families (must be an array)"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cur = conn.cursor()

        # Get existing families to preserve mappings
        cur.execute("""
            SELECT id, family
            FROM group_bill_automation.bill_automator_families
            WHERE user_id = %s
        """, (session['user_id'],))

        existing_families = {}
        for row in cur.fetchall():
            existing_families[row[1]] = row[0]  # family_name -> family_id

        print(f"PUT /api/families - Existing families: {existing_families}")
        print(f"PUT /api/families - New families: {data['families']}")

        families_data = []

        # Process each family
        for family_name in data['families']:
            if family_name in existing_families:
                # Family already exists, keep the existing ID
                family_id = existing_families[family_name]
                print(f"PUT - Preserving existing family: {family_name} (ID: {family_id})")
                families_data.append({
                    "id": family_id,
                    "family": family_name
                })
            else:
                # New family, insert it
                print(f"PUT - Creating new family: {family_name}")
                cur.execute("""
                    INSERT INTO group_bill_automation.bill_automator_families (user_id, family)
                    VALUES (%s, %s)
                    RETURNING id, family
                """, (session['user_id'], family_name))

                family_data = cur.fetchone()
                families_data.append({
                    "id": family_data[0],
                    "family": family_data[1]
                })

        # Remove families that are no longer in the list
        new_family_names = set(data['families'])
        for existing_family_name, existing_family_id in existing_families.items():
            if existing_family_name not in new_family_names:
                # Delete the family (this will cascade delete mappings due to foreign key)
                cur.execute("""
                    DELETE FROM group_bill_automation.bill_automator_families
                    WHERE id = %s
                """, (existing_family_id,))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "message": "Families updated successfully",
            "families": families_data
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/emails', methods=['GET'])
def get_emails():
    """Get all emails for a user."""
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id parameter required"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT id, emails FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (user_id,))
        
        email_data = cur.fetchone()
        emails = email_data[1] if email_data else []
        
        cur.close()
        conn.close()
        
        return jsonify({"emails": emails})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/emails', methods=['POST'])
def create_emails():
    """Create or update emails for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data or 'emails' not in data or not isinstance(data['emails'], list):
            return jsonify({"error": "Missing required field: emails (must be an array)"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if user already has an emails record
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (session['user_id'],))
        
        existing_record = cur.fetchone()
        
        if existing_record:
            # Update existing record
            cur.execute("""
                UPDATE group_bill_automation.bill_automator_emails 
                SET emails = %s 
                WHERE user_id = %s
                RETURNING id, emails
            """, (data['emails'], session['user_id']))
        else:
            # Create new record
            cur.execute("""
                INSERT INTO group_bill_automation.bill_automator_emails (user_id, emails)
                VALUES (%s, %s)
                RETURNING id, emails
            """, (session['user_id'], data['emails']))
        
        email_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Emails saved successfully",
            "emails": email_data[1]
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/emails', methods=['PUT'])
def update_emails():
    """Update emails for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data or 'emails' not in data or not isinstance(data['emails'], list):
            return jsonify({"error": "Missing required field: emails (must be an array)"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if user already has an emails record
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (session['user_id'],))
        
        existing_record = cur.fetchone()
        
        if existing_record:
            # Update existing record
            cur.execute("""
                UPDATE group_bill_automation.bill_automator_emails 
                SET emails = %s 
                WHERE user_id = %s
                RETURNING id, emails
            """, (data['emails'], session['user_id']))
        else:
            # Create new record
            cur.execute("""
                INSERT INTO group_bill_automation.bill_automator_emails (user_id, emails)
                VALUES (%s, %s)
                RETURNING id, emails
            """, (session['user_id'], data['emails']))
        
        email_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Emails updated successfully",
            "emails": email_data[1]
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/onboarding/complete', methods=['POST'])
def complete_onboarding():
    """Mark user onboarding as complete and return updated profile."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        # Get updated profile
        profile = get_user_profile(session['user_id'])
        if not profile:
            return jsonify({"error": "User not found"}), 404
        
        return jsonify({
            "message": "Onboarding completed successfully",
            "profile": profile
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/process_bill', methods=['POST'])
def process_bill():
    """Process bill with conditional logic based on user configuration."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        # Get the PDF file from the request
        if 'pdf' not in request.files:
            return jsonify({"error": "No PDF file provided"}), 400
        
        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({"error": "No PDF file selected"}), 400
        
        # Get user configuration to determine process type
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if user has complete configuration
        cur.execute("""
            SELECT 
                (SELECT COUNT(*) FROM group_bill_automation.bill_automator_families WHERE user_id = %s) as family_count,
                (SELECT COUNT(*) FROM group_bill_automation.bill_automator_emails WHERE user_id = %s) as email_count,
                (SELECT COUNT(*) FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment WHERE user_id = %s) as adjustment_count
        """, (session['user_id'], session['user_id'], session['user_id']))
        
        config_data = cur.fetchone()
        cur.close()
        conn.close()
        
        family_count = config_data[0] or 0
        email_count = config_data[1] or 0
        adjustment_count = config_data[2] or 0
        
        # Determine if user has complete configuration
        has_complete_config = family_count > 0 and email_count > 0 and adjustment_count > 0
        
        if has_complete_config:
            # Quick process - use existing configuration
            pdf_service = PDFService(session['user_id'])
            result = pdf_service.parse_verizon_bill(pdf_file)
            
            if result['success']:
                # Send emails using saved configuration
                # This would integrate with the existing email sending logic
                return jsonify({
                    "message": "Bill processed successfully with saved configuration",
                    "process_type": "quick",
                    "result": result
                })
            else:
                return jsonify({"error": result['error']}), 500
        else:
            # Full process - return configuration requirements
            return jsonify({
                "message": "Configuration required for full processing",
                "process_type": "full",
                "required_config": {
                    "families": family_count,
                    "emails": email_count,
                    "adjustments": adjustment_count
                }
            })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/families/add', methods=['POST'])
def add_family():
    """Add a single family for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data or 'family' not in data or not isinstance(data['family'], str):
            return jsonify({"error": "Missing required field: family (must be a string)"}), 400
        
        family_name = data['family'].strip()
        if not family_name:
            return jsonify({"error": "Family name cannot be empty"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if family already exists for this user
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_families 
            WHERE user_id = %s AND family = %s
        """, (session['user_id'], family_name))
        
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"error": "Family with this name already exists"}), 409
        
        # Insert new family
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_families (user_id, family)
            VALUES (%s, %s)
            RETURNING id, family
        """, (session['user_id'], family_name))
        
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
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/emails/add', methods=['POST'])
def add_email():
    """Add a single email for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data or 'email' not in data or not isinstance(data['email'], str):
            return jsonify({"error": "Missing required field: email (must be a string)"}), 400
        
        email_address = data['email'].strip()
        if not email_address:
            return jsonify({"error": "Email cannot be empty"}), 400
        
        # Basic email validation
        import re
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email_address):
            return jsonify({"error": "Invalid email format"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Check if user already has an emails record
        cur.execute("""
            SELECT id, emails 
            FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (session['user_id'],))
        
        existing_record = cur.fetchone()
        
        if existing_record:
            # Check if email already exists in the array
            existing_emails = existing_record[1] or []
            if email_address in existing_emails:
                cur.close()
                conn.close()
                return jsonify({"error": "Email already exists"}), 409
            
            # Add email to existing array
            updated_emails = existing_emails + [email_address]
            cur.execute("""
                UPDATE group_bill_automation.bill_automator_emails 
                SET emails = %s 
                WHERE user_id = %s
                RETURNING id, emails
            """, (updated_emails, session['user_id']))
        else:
            # Create new record with single email
            cur.execute("""
                INSERT INTO group_bill_automation.bill_automator_emails (user_id, emails)
                VALUES (%s, %s)
                RETURNING id, emails
            """, (session['user_id'], [email_address]))
        
        email_data = cur.fetchone()
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            "message": "Email added successfully",
            "emails": email_data[1]
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/family-mappings', methods=['POST'])
def save_family_mappings():
    """Save phone line to family mappings for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        print(f"Received mappings data: {data}")
        
        if not data or 'mappings' not in data or not isinstance(data['mappings'], list):
            return jsonify({"error": "Missing required field: mappings (must be an array)"}), 400
        
        # Validate that each mapping has required fields
        for i, mapping in enumerate(data['mappings']):
            print(f"Validating mapping {i}: {mapping}")
            if not isinstance(mapping, dict):
                return jsonify({"error": f"Mapping {i} is not a dictionary: {mapping}"}), 400
            if 'family_id' not in mapping:
                return jsonify({"error": f"Mapping {i} missing family_id field: {mapping}"}), 400
            if 'line_id' not in mapping:
                return jsonify({"error": f"Mapping {i} missing line_id field: {mapping}"}), 400
            if not mapping['family_id']:
                return jsonify({"error": f"Mapping {i} has empty family_id: {mapping}"}), 400
            if not mapping['line_id']:
                return jsonify({"error": f"Mapping {i} has empty line_id: {mapping}"}), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        
        # Get existing mappings to avoid duplicates
        cur.execute("""
            SELECT family_id, line_id 
            FROM group_bill_automation.bill_automator_family_mapping 
            WHERE family_id IN (
                SELECT id FROM group_bill_automation.bill_automator_families 
                WHERE user_id = %s
            )
        """, (session['user_id'],))
        
        existing_mappings = set()
        for row in cur.fetchall():
            existing_mappings.add((row[0], row[1]))
        
        # Insert new mappings, avoiding duplicates
        inserted_count = 0
        for mapping in data['mappings']:
            family_id = mapping['family_id']
            line_id = mapping['line_id']
            
            if (family_id, line_id) not in existing_mappings:
                cur.execute("""
                    INSERT INTO group_bill_automation.bill_automator_family_mapping 
                    (family_id, line_id) 
                    VALUES (%s, %s)
                """, (family_id, line_id))
                inserted_count += 1
            else:
                # Mapping already exists, skip
                pass
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "message": f"Family mappings saved successfully ({inserted_count} new mappings added)",
            "mappings_count": len(data['mappings']),
            "inserted_count": inserted_count
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/lines', methods=['GET'])
def get_lines():
    """Get all available phone lines for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, number, device, created_at
            FROM group_bill_automation.bill_automator_lines 
            WHERE user_id = %s
            ORDER BY id
        """, (session['user_id'],))
        
        lines = []
        for line in cur.fetchall():
            lines.append({
                "id": line[0],
                "name": line[1],
                "number": line[2],
                "device": line[3],
                "created_at": line[4].isoformat() if line[4] else None
            })
        
        cur.close()
        conn.close()
        
        return jsonify({"lines": lines})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# @app.route('/api/parse-pdf', methods=['POST'])
# def parse_pdf():
#     """Parse PDF and extract line data, checking against existing lines in database."""
#     if 'user_id' not in session:
#         return jsonify({"error": "Not authenticated"}), 401
    
#     try:
#         # Get the PDF file from the request
#         if 'pdf' not in request.files:
#             return jsonify({"error": "No PDF file provided"}), 400
        
#         pdf_file = request.files['pdf']
#         if pdf_file.filename == '':
#             return jsonify({"error": "No PDF file selected"}), 400
        
#         # Use the PDF service to parse the bill
#         pdf_service = PDFService(session['user_id'])
#         result = pdf_service.parse_verizon_bill(pdf_file)
        
#         if not result['success']:
#             return jsonify({"error": result['error']}), 500
        
#         # Get existing lines from database for this user
#         conn = get_db_connection()
#         if not conn:
#             return jsonify({"error": "Database connection failed"}), 500
        
#         cur = conn.cursor()
#         cur.execute("""
#             SELECT id, name, number, device
#             FROM group_bill_automation.bill_automator_lines 
#             WHERE user_id = %s
#         """, (session['user_id'],))
        
#         existing_lines = {}
#         for line in cur.fetchall():
#             existing_lines[line[2]] = {  # key by phone number
#                 "id": line[0],
#                 "name": line[1],
#                 "number": line[2],
#                 "device": line[3],
#                 "exists": True
#             }
        
#         # Process parsed charges and check against existing lines
#         parsed_lines = []
#         new_lines = []
        
#         for name, charge in result['charges'].items():
#             # Get line details from enhanced parsing
#             line_detail = result.get('line_details', {}).get(name, {})
#             phone_number = line_detail.get('number', 'Unknown')
#             device = line_detail.get('device', 'Unknown')
            
#             line_data = {
#                 "name": name,
#                 "number": phone_number,
#                 "device": device,
#                 "charge": charge,
#                 "exists": phone_number in existing_lines and phone_number != 'Unknown'
#             }
            
#             if line_data["exists"]:
#                 # Update existing line with new charge
#                 existing_line = existing_lines[phone_number]
#                 line_data["id"] = existing_line["id"]
#                 line_data["device"] = existing_line["device"]
                
#                 # Note: We don't store charges in the lines table, they're calculated from PDF parsing
#                 # Just update the line info if needed
#                 cur.execute("""
#                     UPDATE group_bill_automation.bill_automator_lines 
#                     SET name = %s, device = %s, updated_at = NOW()
#                     WHERE id = %s
#                 """, (name, device, existing_line["id"]))
#             else:
#                 # Add new line to database (without charge - charges are from PDF parsing)
#                 cur.execute("""
#                     INSERT INTO group_bill_automation.bill_automator_lines 
#                     (user_id, name, number, device, created_at, updated_at)
#                     VALUES (%s, %s, %s, %s, NOW(), NOW())
#                     RETURNING id
#                 """, (session['user_id'], name, phone_number, device))
                
#                 line_data["id"] = cur.fetchone()[0]
#                 new_lines.append(line_data)
            
#             parsed_lines.append(line_data)
        
#         conn.commit()
#         cur.close()
#         conn.close()
        
#         return jsonify({
#             "success": True,
#             "lines": parsed_lines,
#             "new_lines_count": len(new_lines),
#             "existing_lines_count": len(parsed_lines) - len(new_lines),
#             "total_charge": sum(line["charge"] for line in parsed_lines)
#         })
    
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500

@app.route('/api/parse-pdf', methods=['POST'])
def parse_pdf():
    """Parse PDF and extract line data without saving to database."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        # Get the PDF file from the request
        if 'pdf' not in request.files:
            return jsonify({"error": "No PDF file provided"}), 400
        
        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({"error": "No PDF file selected"}), 400
        
        # Read the PDF file
        pdf_bytes = pdf_file.read()
        
        # Parse the PDF using the updated extract_charges_from_pdf function
        account_wide_value, line_details = extract_charges_from_pdf(pdf_bytes)
        
        # Get existing lines from database for this user
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, number, device
            FROM group_bill_automation.bill_automator_lines 
            WHERE user_id = %s
        """, (session['user_id'],))
        
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
        
        print(f"=== MANUAL PROCESS DEBUG ===")
        print(f"Account-wide value from PDF: {account_wide_value}")
        print(f"Number of line details from PDF: {len(line_details)}")
        print(f"Number of existing lines from DB: {len(existing_lines)}")
        
        # Check specific line IDs that might be missing
        print(f"\n--- CHECKING SPECIFIC LINE IDs IN MANUAL PROCESS ---")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT fm.id, fm.family_id, fm.line_id, f.family, l.name as line_name, l.number as line_number
            FROM group_bill_automation.bill_automator_family_mapping fm
            JOIN group_bill_automation.bill_automator_families f ON fm.family_id = f.id
            JOIN group_bill_automation.bill_automator_lines l ON fm.line_id = l.id
            WHERE f.user_id = %s AND fm.line_id IN (55, 60)
            ORDER BY fm.line_id
        """, (session['user_id'],))
        
        specific_mappings = cur.fetchall()
        print(f"Specific mappings for line_id 55 and 60:")
        for mapping in specific_mappings:
            print(f"  mapping_id={mapping[0]}, family_id={mapping[1]}, line_id={mapping[2]}, family_name='{mapping[3]}', line_name='{mapping[4]}', line_number='{mapping[5]}'")
        
        cur.close()
        conn.close()
        
        # Print all existing lines from database
        print(f"\n--- EXISTING LINES FROM DATABASE ---")
        for composite_key, line_data in existing_lines.items():
            print(f"DB Line: key='{composite_key}', id={line_data['id']}, name='{line_data['name']}', number='{line_data['number']}', device='{line_data['device']}'")
        
        # Print all parsed lines from PDF
        print(f"\n--- PARSED LINES FROM PDF ---")
        for line_key, line_data in line_details.items():
            print(f"PDF Line: name='{line_data.get('name')}', number='{line_data.get('number')}', device='{line_data.get('device')}', charge={line_data.get('charge')}")
        
        # Process parsed line details and check against existing lines (without saving)
        parsed_lines = []

        for unique_key, line_detail in line_details.items():
            name = line_detail["name"]
            device = line_detail["device"]
            number = line_detail["number"]
            charge = line_detail["charge"]

            # Create composite key for this parsed line
            parsed_composite_key = f"{name}|{number}"

            exists = parsed_composite_key in existing_lines and number != 'Unknown'

            print(f"\n--- CHECKING LINE: {name}|{number} ---")
            print(f"Looking for composite key: '{parsed_composite_key}'")
            print(f"Found in existing_lines: {parsed_composite_key in existing_lines}")
            print(f"Number is 'Unknown': {number == 'Unknown'}")
            print(f"Final exists result: {exists}")
            
            if parsed_composite_key in existing_lines:
                print(f"  Found existing line: {existing_lines[parsed_composite_key]}")

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
        
        print(f"\n--- SUMMARY ---")
        print(f"Total parsed lines: {len(parsed_lines)}")
        print(f"Existing lines found: {len([line for line in parsed_lines if line['exists']])}")
        print(f"New lines to save: {len([line for line in parsed_lines if not line['exists']])}")
        print(f"Total charge: ${sum(line['charge'] for line in parsed_lines)}")
        print(f"=== END MANUAL PROCESS DEBUG ===")
        
        return jsonify({
            "success": True,
            "lines": parsed_lines,
            "existing_lines_count": len([line for line in parsed_lines if line["exists"]]),
            "new_lines_count": len([line for line in parsed_lines if not line["exists"]]),
            "total_charge": sum(line["charge"] for line in parsed_lines),
            "account_wide_value": account_wide_value
        })
    
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/save-selected-lines', methods=['POST'])
def save_selected_lines():
    """Save only the selected lines to the database."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
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
                """, (session['user_id'], line['name'], line['number'], line['device']))
                
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
            "saved_lines": saved_lines,
            "message": f"Saved {len([line for line in saved_lines if not line.get('was_existing', False)])} new lines"
        })
    
    except Exception as e:
        print(f"Error saving selected lines: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/family-mappings', methods=['GET'])
def get_family_mappings():
    """Get existing family mappings for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT fm.id, fm.family_id, fm.line_id, f.family, l.name as line_name, l.number as line_number, l.device as line_device
            FROM group_bill_automation.bill_automator_family_mapping fm
            JOIN group_bill_automation.bill_automator_families f ON fm.family_id = f.id
            JOIN group_bill_automation.bill_automator_lines l ON fm.line_id = l.id
            WHERE f.user_id = %s
            ORDER BY fm.id
        """, (session['user_id'],))
        
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
        print(f"Error getting family mappings: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/accountwide-reconciliation', methods=['GET'])
def get_accountwide_reconciliation():
    """Get account-wide reconciliation for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cur = conn.cursor()
        cur.execute("""
            SELECT reconciliation 
            FROM group_bill_automation.bill_automator_accountwide_reconciliation 
            WHERE user_id = %s
        """, (session['user_id'],))
        
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
def save_accountwide_reconciliation():
    """Save account-wide reconciliation settings for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
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
        """, (session['user_id'],))
        
        # Insert new reconciliation
        cur.execute("""
            INSERT INTO group_bill_automation.bill_automator_accountwide_reconciliation 
            (user_id, reconciliation) 
            VALUES (%s, %s)
            RETURNING id
        """, (session['user_id'], reconciliation))
        
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
def get_line_discount_transfer():
    """Get line discount transfer for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
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
        """, (session['user_id'],))
        
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
def save_line_discount_transfer():
    """Save line discount transfer adjustment for the authenticated user."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
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
        """, (line_to_remove_from, line_to_add_to, session['user_id']))
        
        lines = cur.fetchall()
        if len(lines) != 2:
            return jsonify({"error": "One or both lines not found or do not belong to user"}), 400
        
        # Check if an existing transfer exists for this user with the same remove/add lines
        cur.execute("""
            SELECT id FROM group_bill_automation.bill_automator_line_discount_transfer_adjustment 
            WHERE user_id = %s AND line_to_remove_from = %s AND line_to_add_to = %s
        """, (session['user_id'], line_to_remove_from, line_to_add_to))
        
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
            """, (session['user_id'], transfer_amount, line_to_remove_from, line_to_add_to))
            
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

@app.route('/api/send-bill-emails', methods=['POST'])
def send_bill_emails():
    """Send bill emails with family totals to configured email addresses."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
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
        """, (session['user_id'],))
        
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
        """, (session['user_id'],))
        
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
def automated_process():
    """Fully automated bill processing using saved configuration."""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
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
        cur.execute("""
            SELECT f.id, f.family, fm.line_id, l.name as line_name, l.number as line_number, l.device as line_device
            FROM group_bill_automation.bill_automator_families f
            LEFT JOIN group_bill_automation.bill_automator_family_mapping fm ON f.id = fm.family_id
            LEFT JOIN group_bill_automation.bill_automator_lines l ON fm.line_id = l.id
            WHERE f.user_id = %s
            ORDER BY f.id, fm.id
        """, (session['user_id'],))
        
        family_mappings = cur.fetchall()
        
        print(f"=== AUTOMATED PROCESSING DEBUG ===")
        print(f"Raw family mappings query results:")
        for i, mapping in enumerate(family_mappings):
            print(f"  {i}: family_id={mapping[0]}, family_name='{mapping[1]}', line_id={mapping[2]}, line_name='{mapping[3]}', line_number='{mapping[4]}', line_device='{mapping[5]}'")
        
        # Check specific line IDs that might be missing
        print(f"\n--- CHECKING SPECIFIC LINE IDs ---")
        cur.execute("""
            SELECT fm.id, fm.family_id, fm.line_id, f.family, l.name as line_name, l.number as line_number
            FROM group_bill_automation.bill_automator_family_mapping fm
            JOIN group_bill_automation.bill_automator_families f ON fm.family_id = f.id
            JOIN group_bill_automation.bill_automator_lines l ON fm.line_id = l.id
            WHERE f.user_id = %s AND fm.line_id IN (55, 60)
            ORDER BY fm.line_id
        """, (session['user_id'],))
        
        specific_mappings = cur.fetchall()
        print(f"Specific mappings for line_id 55 and 60:")
        for mapping in specific_mappings:
            print(f"  mapping_id={mapping[0]}, family_id={mapping[1]}, line_id={mapping[2]}, family_name='{mapping[3]}', line_name='{mapping[4]}', line_number='{mapping[5]}'")
        
        # Get user's emails
        cur.execute("""
            SELECT emails FROM group_bill_automation.bill_automator_emails 
            WHERE user_id = %s
        """, (session['user_id'],))
        
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
        """, (session['user_id'],))
        
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
        """, (session['user_id'],))
        
        line_adjustments = cur.fetchall()
        
        # Get user's account-wide reconciliation
        cur.execute("""
            SELECT reconciliation
            FROM group_bill_automation.bill_automator_accountwide_reconciliation 
            WHERE user_id = %s
        """, (session['user_id'],))
        
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
            account_wide_value, line_details = extract_charges_from_pdf(pdf_bytes)
            
            # Step 2: Calculate family totals based on line mappings
            family_totals = {}
            
            print(f"=== AUTOMATED PROCESSING DEBUG ===")
            print(f"Account-wide value from PDF: {account_wide_value}")
            print(f"Number of line details from PDF: {len(line_details)}")
            print(f"Number of family mappings from DB: {len(family_mappings)}")
            
            # Print all parsed lines from PDF
            print(f"\n--- PARSED LINES FROM PDF ---")
            for line_key, line_data in line_details.items():
                print(f"PDF Line: name='{line_data.get('name')}', number='{line_data.get('number')}', device='{line_data.get('device')}', charge={line_data.get('charge')}")
            
            # Print all family mappings from database
            print(f"\n--- FAMILY MAPPINGS FROM DATABASE ---")
            for family_id, family_name, line_id, line_name, line_number, line_device in family_mappings:
                print(f"DB Mapping: family='{family_name}', name='{line_name}', number='{line_number}', device='{line_device}', line_id={line_id}")
            
            # Group charges by family based on line mappings
            for family_id, family_name, line_id, line_name, line_number, line_device in family_mappings:
                if family_name not in family_totals:
                    family_totals[family_name] = 0
                
                print(f"\n--- CHECKING FAMILY: {family_name} ---")
                print(f"Looking for: name='{line_name}', number='{line_number}'")
                
                # Find charges for this line by matching name and number
                for line_key, line_data in line_details.items():
                    pdf_name = line_data.get('name')
                    pdf_number = line_data.get('number')
                    pdf_charge = line_data.get('charge', 0)
                    
                    print(f"  Comparing with PDF: name='{pdf_name}', number='{pdf_number}', charge={pdf_charge}")
                    
                    if (pdf_name == line_name and pdf_number == line_number):
                        print(f"  ✅ MATCH FOUND! Adding {pdf_charge} to {family_name}")
                        family_totals[family_name] += pdf_charge
                    else:
                        print(f"  ❌ NO MATCH")
            
            print(f"\n--- FAMILY TOTALS BEFORE ADJUSTMENTS ---")
            for family_name, total in family_totals.items():
                print(f"{family_name}: ${total}")
            
            # Step 3: Apply line adjustments (discount transfers)
            print(f"\n--- LINE ADJUSTMENTS ---")
            print(f"Number of line adjustments: {len(line_adjustments)}")
            
            for transfer_amount, line_to_remove_from, line_to_add_to in line_adjustments:
                # Convert decimal to float for arithmetic operations
                transfer_amount_float = float(transfer_amount)
                print(f"Processing transfer: ${transfer_amount_float} from line_id={line_to_remove_from} to line_id={line_to_add_to}")
                
                # Find which family the lines belong to
                for family_id, family_name, line_id, line_name, line_number, line_device in family_mappings:
                    if line_id == line_to_remove_from:
                        print(f"  Removing ${transfer_amount_float} from {family_name}")
                        family_totals[family_name] -= transfer_amount_float
                    elif line_id == line_to_add_to:
                        print(f"  Adding ${transfer_amount_float} to {family_name}")
                        family_totals[family_name] += transfer_amount_float
            
            # Step 4: Apply account-wide reconciliation if configured
            print(f"\n--- ACCOUNT-WIDE RECONCILIATION ---")
            print(f"Reconciliation value: {account_wide_reconciliation}")
            
            if account_wide_reconciliation:
                if account_wide_reconciliation == "evenly":
                    # Distribute account-wide charges/credits equally among families
                    num_families = len(set(f[1] for f in family_mappings))  # unique family names
                    if num_families > 0:
                        per_family_share = account_wide_value / num_families
                        print(f"Distributing account-wide value (${account_wide_value}) evenly among {num_families} families: ${per_family_share} each")
                        for family_name in family_totals:
                            print(f"  Adding ${per_family_share} to {family_name}")
                            family_totals[family_name] += per_family_share
                else:
                    # Try to parse as a numeric value
                    try:
                        account_wide_amount = float(account_wide_reconciliation)
                        # Distribute account-wide amount equally among families
                        num_families = len(set(f[1] for f in family_mappings))  # unique family names
                        if num_families > 0:
                            per_family_share = account_wide_amount / num_families
                            print(f"Distributing reconciliation amount (${account_wide_amount}) evenly among {num_families} families: ${per_family_share} each")
                            for family_name in family_totals:
                                print(f"  Adding ${per_family_share} to {family_name}")
                                family_totals[family_name] += per_family_share
                    except ValueError:
                        # If reconciliation is not a valid number, skip it
                        print(f"Reconciliation value '{account_wide_reconciliation}' is not a valid number, skipping")
                        pass
            else:
                print("No account-wide reconciliation configured")
            
            # Step 5: Send emails using the existing functionality
            try:
                # Convert family totals to the format expected by parse_verizon.send_email
                person_totals = family_totals  # The function can handle family names as person names
                
                # Send email using the existing functionality
                parse_verizon.send_email(person_totals, emails, user_email)
                
            except Exception as e:
                return jsonify({"error": f"Failed to send emails: {str(e)}"}), 500
            
            total_amount = sum(family_totals.values())
            
            print(f"\n--- FINAL FAMILY TOTALS ---")
            for family_name, total in family_totals.items():
                print(f"{family_name}: ${total}")
            print(f"Total amount: ${total_amount}")
            print(f"=== END AUTOMATED PROCESSING DEBUG ===")
            
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
