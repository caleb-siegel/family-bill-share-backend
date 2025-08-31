# Vercel Backend Deployment Debug Guide

## Issues Fixed:

1. **Missing API Structure**: Created proper `api/` directory structure for Vercel
2. **Missing Vercel Configuration**: Created `vercel.json` file with correct function mapping
3. **Session Issues**: Completely removed Flask-Session, using JWT tokens only
4. **Simplified API**: Created minimal working version for deployment

## Files Created/Modified:

- `backend/api/index.py` - Simplified Flask app with JWT authentication only
- `backend/api/requirements.txt` - Python dependencies (removed Flask-Session)
- `backend/vercel.json` - Vercel deployment configuration

## Directory Structure:

```
backend/
├── api/
│   ├── index.py          # Simplified Flask app with JWT auth
│   └── requirements.txt  # Dependencies (no Flask-Session)
├── vercel.json           # Vercel config
└── app.py               # Original app (for local dev)
```

## Current Endpoints:

- `GET /api/health` - Health check
- `POST /api/auth/signup` - User registration (returns JWT token)
- `POST /api/auth/signin` - User login (returns JWT token)
- `GET /api/auth/check` - Check authentication (requires JWT)
- `POST /api/auth/signout` - Sign out (requires JWT)

## Testing Steps:

1. **Deploy to Vercel** with these changes
2. **Test Health Endpoint**: Visit `https://family-bill-share-backend.vercel.app/api/health`
3. **Test Signup**: Should return JWT token
4. **Test Signin**: Should return JWT token
5. **Test Check**: Should work with JWT authentication

## Environment Variables Needed in Vercel:

- `SQLALCHEMY_DATABASE_URI` - Your Supabase connection string
- `SECRET_KEY` - A secure secret key for JWT signing
- `FLASK_ENV` - Set to "production"

## Frontend Changes:

The frontend now:
- Stores JWT tokens in localStorage
- Sends tokens in Authorization headers
- Uses `api.signin()`, `api.checkAuth()` for authentication

## Next Steps:

After successful deployment, you can gradually add back the other endpoints (families, emails, etc.) with JWT authentication.
