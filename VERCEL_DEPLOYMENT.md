# Vercel Backend Deployment Debug Guide

## Issues Fixed:

1. **Missing API Structure**: Created proper `api/` directory structure for Vercel
2. **Missing Vercel Configuration**: Created `vercel.json` file with correct function mapping
3. **Session Issues**: Replaced Flask-Session with JWT tokens for Vercel compatibility
4. **Added Health Check**: Created `/api/health` endpoint for testing

## Files Created/Modified:

- `backend/api/index.py` - Main Flask application with JWT authentication
- `backend/api/requirements.txt` - Python dependencies (added PyJWT)
- `backend/api/services/` - PDF service directory
- `backend/api/parse_verizon.py` - Verizon parsing module
- `backend/vercel.json` - Vercel deployment configuration
- `frontend/family-bill-share/src/lib/api.ts` - Updated to use JWT tokens

## Authentication Changes:

- **Backend**: Switched from Flask-Session to JWT tokens
- **Frontend**: Updated to send JWT tokens in Authorization headers
- **Token Storage**: Tokens stored in localStorage for persistence

## Directory Structure:

```
backend/
├── api/
│   ├── index.py          # Main Flask app with JWT auth
│   ├── requirements.txt  # Dependencies (includes PyJWT)
│   ├── services/         # PDF service
│   └── parse_verizon.py  # Verizon parsing
├── vercel.json           # Vercel config
└── app.py               # Original app (for local dev)
```

## Testing Steps:

1. **Deploy to Vercel** with these changes
2. **Test Health Endpoint**: Visit `https://family-bill-share-backend.vercel.app/api/health`
3. **Test Signin**: Should return JWT token
4. **Test Check/Profile**: Should work with JWT authentication

## Environment Variables Needed in Vercel:

- `SQLALCHEMY_DATABASE_URI` - Your Supabase connection string
- `SECRET_KEY` - A secure secret key for JWT signing
- `FLASK_ENV` - Set to "production"

## Frontend Changes:

The frontend now:
- Stores JWT tokens in localStorage
- Sends tokens in Authorization headers
- Handles token expiration automatically
- Uses `api.signin()`, `api.checkAuth()`, `api.getProfile()` for authentication
