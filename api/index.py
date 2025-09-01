"""
Simple Flask API for Verizon Family Plan Bill Automation.
Connects directly to Supabase without ORM complexity.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os

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

# API Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "message": "API is running"})

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """Simple test endpoint."""
    return jsonify({"message": "Test endpoint working"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
