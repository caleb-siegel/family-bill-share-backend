# Verizon Family Plan Bill Automation - Backend

A simple Flask API that connects directly to Supabase for managing Verizon family plan bills.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables
Create a `.env` file in the backend directory:
```env
SQLALCHEMY_DATABASE_URI=postgresql://username:password@host:port/database
SENDINBLUE_API_KEY=your_sendinblue_api_key
```

### 3. Create Database Tables
Run the `create_tables.sql` script in your Supabase SQL editor to create all required tables.

### 4. Run the API
```bash
python app.py
```

The API will be available at `http://localhost:5000`

## 🗄️ Database Schema

All tables are created in the `group_bill_automation` schema:

- **`bill_automator_users`** - User accounts
- **`bill_automator_families`** - Family groups for each user
- **`bill_automator_family_mapping`** - Line names mapped to families
- **`bill_automator_emails`** - Email lists for each user
- **`bill_automator_templates`** - Email templates
- **`bill_automator_line_discount_transfer_adjustment`** - Line adjustments
- **`bill_automator_accountwide_reconciliation`** - Account-wide settings

## 📡 API Endpoints

### Health Check
- `GET /api/health` - Check if API is running

### PDF Processing
- `POST /api/parse_pdf` - Parse Verizon PDF and send emails

### Users
- `GET /api/users` - Get all users
- `POST /api/users` - Create new user

### Families
- `GET /api/families?user_id=X` - Get families for a user

## 🔧 Architecture

- **Flask** - Web framework
- **psycopg2** - Direct PostgreSQL connection
- **No ORM** - Direct SQL queries for simplicity
- **Supabase** - Database hosting
- **Existing parse_verizon.py** - PDF processing logic preserved

## 💡 Why This Approach?

- ✅ **Simple & Reliable** - No complex ORM setup
- ✅ **Direct Control** - Full control over SQL queries
- ✅ **Easy Debugging** - No abstraction layers
- ✅ **Fast Development** - Get APIs working quickly
- ✅ **No Migration Issues** - Tables created directly in Supabase

## 🚫 What We Removed

- ❌ Flask-SQLAlchemy (ORM complexity)
- ❌ Flask-Migrate/Alembic (migration headaches)
- ❌ Complex model definitions
- ❌ Schema management issues

## 🔮 Future Enhancements

- Add authentication middleware
- Add more CRUD endpoints
- Add input validation
- Add error logging
- Add rate limiting