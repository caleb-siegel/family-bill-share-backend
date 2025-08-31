# Vercel Backend Deployment Debug Guide

## Issues Fixed:

1. **Missing API Structure**: Created proper `api/` directory structure for Vercel
2. **Missing Vercel Configuration**: Created `vercel.json` file with correct function mapping
3. **Session Configuration**: Updated to use `/tmp` directory for Vercel compatibility
4. **Added Health Check**: Created `/api/health` endpoint for testing

## Files Created/Modified:

- `backend/api/index.py` - Main Flask application (copied from app.py)
- `backend/api/requirements.txt` - Python dependencies
- `backend/api/services/` - PDF service directory
- `backend/api/parse_verizon.py` - Verizon parsing module
- `backend/vercel.json` - Vercel deployment configuration
- `backend/app.py` - Updated session configuration (original file)

## Directory Structure:

```
backend/
├── api/
│   ├── index.py          # Main Flask app for Vercel
│   ├── requirements.txt  # Dependencies
│   ├── services/         # PDF service
│   └── parse_verizon.py  # Verizon parsing
├── vercel.json           # Vercel config
└── app.py               # Original app (for local dev)
```

## Testing Steps:

1. **Deploy to Vercel** with these changes
2. **Test Health Endpoint**: Visit `https://family-bill-share-backend.vercel.app/api/health`
3. **Test Signin**: Should work as before
4. **Test Check/Profile**: Should now work with the session fixes

## Common Issues:

- **Session Persistence**: Sessions now use `/tmp` directory which should work on Vercel
- **Database Connection**: Make sure your `SQLALCHEMY_DATABASE_URI` environment variable is set in Vercel
- **CORS**: Already configured to accept requests from your frontend

## Environment Variables Needed in Vercel:

- `SQLALCHEMY_DATABASE_URI` - Your Supabase connection string
- `SECRET_KEY` - A secure secret key for sessions
- `FLASK_ENV` - Set to "production"

## If Issues Persist:

1. Check Vercel deployment logs
2. Test the health endpoint first
3. Verify environment variables are set correctly
4. Check if database connection is working
