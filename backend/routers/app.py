from fastapi import FastAPI, Request, Response, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
import os
import sqlite3
import jwt
from datetime import datetime, timedelta
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import string
import bcrypt

templates = Jinja2Templates(directory="templates")


# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Add SessionMiddleware for OAuth flow
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "some-random-string"))
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure OAuth with Google
oauth = OAuth()
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    client_kwargs={'scope': 'openid email profile'},
)

# Database connection function
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn

# User model
class User:
    def __init__(self, id, email, name, google_sub=None, password=None):
        self.id = id
        self.email = email
        self.name = name
        self.google_sub = google_sub
        self.password = password

# Function to get or create a user based on Google userinfo
def get_or_create_user(userinfo):
    db = get_db()
    cursor = db.cursor()
    sub = userinfo['sub']
    email = userinfo['email']
    name = userinfo.get('name', '')
    cursor.execute("SELECT * FROM users WHERE google_sub = ?", (sub,))
    row = cursor.fetchone()
    if row:
        user = User(id=row['id'], email=row['email'], name=row['name'], google_sub=row['google_sub'])
    else:
        cursor.execute("INSERT INTO users (google_sub, email, name) VALUES (?, ?, ?)", (sub, email, name))
        db.commit()
        user_id = cursor.lastrowid
        user = User(id=user_id, email=email, name=name, google_sub=sub)
    db.close()
    return user

# JWT configuration
SECRET_KEY = os.getenv("JWT_SECRET", "your-secret-key")
ALGORITHM = "HS256"

# Function to generate JWT token
def generate_jwt_token(user):
    payload = {
        "sub": str(user.id),  # User ID as the subject
        "exp": datetime.now(datetime.timezone.utc) + timedelta(hours=1),  # Token expires in 1 hour
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token

# Function to verify password
def verify_password(stored_password, provided_password):
    if stored_password and provided_password:
        return bcrypt.checkpw(provided_password.encode('utf-8'), stored_password)
    return False

# Endpoint to initiate Google login
@app.get("/login/google")
async def login_via_google(request: Request):
    redirect_uri = request.url_for('auth_via_google')
    return await oauth.google.authorize_redirect(request, redirect_uri)

# Endpoint to handle Google callback
@app.get("/auth/google")
async def auth_via_google(request: Request):
    try:
        print("Starting Google auth callback...")
        token = await oauth.google.authorize_access_token(request)
        print(f"Got OAuth token, userinfo: {token.get('userinfo', {}).get('email')}")
        
        userinfo = token['userinfo']
        user = get_or_create_user(userinfo)
        print(f"Got/Created user with ID: {user.id}")
        
        jwt_token = generate_jwt_token(user)
        print("Generated JWT token")
        
        response = RedirectResponse(url="/dashboard")
        response.set_cookie(
            key="access_token",
            value=jwt_token,
            httponly=True,  # Prevent JavaScript access
            secure=False,  # Set to True in production for HTTPS
            samesite="lax"  # Mitigate CSRF
        )
        print("Set cookie and redirecting to dashboard")
        return response
    except Exception as e:
        print(f"Auth error: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return RedirectResponse(url="/login")

# JWT authentication dependency
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return User(id=row['id'], email=row['email'], name=row['name'], google_sub=row['google_sub'])
        else:
            raise HTTPException(status_code=401, detail="User not found")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Email signup endpoint
@app.post("/signup")
async def signup(request: Request):
    try:
        form_data = await request.json()
        email = form_data.get('email')
        password = form_data.get('password')
        name = form_data.get('name')
        
        if not email or not password or not name:
            return JSONResponse({"error": "Name, email and password are required"}, status_code=400)
        
        # Hash the password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        db = get_db()
        cursor = db.cursor()
        
        # Check if email already exists
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            db.close()
            return JSONResponse({"error": "Email already registered"}, status_code=400)
        
        # Create new user
        cursor.execute(
            "INSERT INTO users (email, password, name) VALUES (?, ?, ?)",
            (email, hashed_password, name)
        )
        db.commit()
        user_id = cursor.lastrowid
        
        # Generate JWT token
        user = User(id=user_id, email=email, name=name)
        token = generate_jwt_token(user)
        
        db.close()
        
        # Create response with redirect and cookie
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=False,  # Set to True in production for HTTPS
            samesite="lax"
        )
        return response
        
    except Exception as e:
        print(f"Signup error: {str(e)}")
        return JSONResponse({"error": "An error occurred during signup"}, status_code=500)

# Email login endpoint
@app.post("/login")
async def login(request: Request):
    try:
        form_data = await request.json()
        email = form_data.get('email')
        password = form_data.get('password')
        
        if not email or not password:
            return JSONResponse({"error": "Email and password are required"}, status_code=400)
        
        db = get_db()
        cursor = db.cursor()
        
        # Get user by email
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user_data = cursor.fetchone()
        
        if not user_data:
            db.close()
            return JSONResponse({"error": "Invalid email or password"}, status_code=401)
        
        stored_password = user_data['password']
        if not stored_password:
            db.close()
            return JSONResponse({"error": "Invalid email or password"}, status_code=401)
            
        # Convert stored_password from bytes to string if needed
        if isinstance(stored_password, bytes):
            stored_password = stored_password.decode('utf-8')
            
        # Convert input password to bytes for comparison
        password_bytes = password.encode('utf-8')
        stored_password_bytes = stored_password.encode('utf-8') if isinstance(stored_password, str) else stored_password
        
        # Verify password
        if not bcrypt.checkpw(password_bytes, stored_password_bytes):
            db.close()
            return JSONResponse({"error": "Invalid email or password"}, status_code=401)
        
        # Generate JWT token
        user = User(
            id=user_data['id'],
            email=user_data['email'],
            name=user_data['name'] or email.split('@')[0],
            password=None  # Don't include password in token
        )
        token = generate_jwt_token(user)
        
        db.close()
        
        # Create response with redirect and cookie
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=False,  # Set to True in production for HTTPS
            samesite="lax"
        )
        return response
        
    except Exception as e:
        print(f"Login error: {str(e)}")
        return JSONResponse({"error": "An error occurred during login"}, status_code=500)

# Email template for password reset
def get_reset_email_template(reset_token: str) -> str:
    return f"""
Dear User,

You have requested to reset your password for your Cognigrade account.

Your One-Time Password (OTP) is: {reset_token}

This OTP will expire in 15 minutes. Please do not share this OTP with anyone.

If you did not request this password reset, please ignore this email.

Best regards,
Cognigrade Team
"""

# Function to send reset password email
def send_reset_email(email: str, reset_token: str):
    try:
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_username = os.getenv("SMTP_USERNAME")
        smtp_password = os.getenv("SMTP_PASSWORD")

        if not smtp_username or not smtp_password:
            print("Error: SMTP credentials not found in environment variables")
            return False

        msg = MIMEMultipart()
        msg["From"] = smtp_username
        msg["To"] = email
        msg["Subject"] = "Password Reset OTP - Cognigrade"

        # Use the common email template
        body = get_reset_email_template(reset_token)
        msg.attach(MIMEText(body, "plain"))

        try:
            # Create SMTP connection
            print(f"Connecting to SMTP server {smtp_server}:{smtp_port}")
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.set_debuglevel(1)  # Enable debugging
            
            # Start TLS
            print("Starting TLS")
            server.starttls()
            
            # Login
            print(f"Attempting to login with username: {smtp_username}")
            server.login(smtp_username, smtp_password)
            
            # Send email
            print(f"Sending email to: {email}")
            server.send_message(msg)
            
            # Quit
            server.quit()
            print("Email sent successfully")
            return True
            
        except smtplib.SMTPAuthenticationError:
            print("SMTP Authentication failed. Please check your email and App Password")
            print("Note: For Gmail, you need to use an App Password instead of your regular password")
            print("To create an App Password:")
            print("1. Go to your Google Account settings")
            print("2. Select 'Security'")
            print("3. Under 'Signing in to Google', select '2-Step Verification'")
            print("4. At the bottom, select 'App passwords'")
            print("5. Generate a new App Password for 'Mail'")
            return False
            
        except smtplib.SMTPException as smtp_error:
            print(f"SMTP error occurred: {str(smtp_error)}")
            return False
            
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return False

# Generate random OTP
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

# Forgot password endpoint
@app.post("/forgot-password")
async def forgot_password(email: str = Form(...)):
    db = get_db()
    cursor = db.cursor()
    
    # Check if user exists
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    
    if not user:
        db.close()
        return JSONResponse({"error": "Email not found"}, status_code=404)
    
    # Generate OTP and set expiry
    reset_token = generate_otp()
    expiry = datetime.utcnow() + timedelta(minutes=15)
    
    # Update database with reset token
    cursor.execute(
        "UPDATE users SET reset_token = ?, reset_token_expiry = ? WHERE email = ?",
        (reset_token, expiry, email)
    )
    db.commit()
    
    # Send reset email
    if send_reset_email(email, reset_token):
        db.close()
        return JSONResponse({"message": "Reset OTP sent to your email"})
    else:
        db.close()
        return JSONResponse({"error": "Failed to send reset email"}, status_code=500)

# Verify OTP endpoint
@app.post("/verify-otp")
async def verify_otp(email: str = Form(...), otp: str = Form(...)):
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute(
        "SELECT reset_token, reset_token_expiry FROM users WHERE email = ?",
        (email,)
    )
    result = cursor.fetchone()
    
    if not result or not result['reset_token'] or not result['reset_token_expiry']:
        db.close()
        return JSONResponse({"error": "Invalid reset request"}, status_code=400)
    
    token_expiry = datetime.fromisoformat(result['reset_token_expiry'].replace('Z', '+00:00'))
    
    if datetime.utcnow() > token_expiry:
        db.close()
        return JSONResponse({"error": "OTP has expired"}, status_code=400)
    
    if result['reset_token'] != otp:
        db.close()
        return JSONResponse({"error": "Invalid OTP"}, status_code=400)
    
    db.close()
    return JSONResponse({"message": "OTP verified successfully"})

# Reset password endpoint
@app.post("/reset-password")
async def reset_password(
    email: str = Form(...),
    otp: str = Form(...),
    new_password: str = Form(...)
):
    db = get_db()
    cursor = db.cursor()
    
    # Verify OTP again
    cursor.execute(
        "SELECT reset_token, reset_token_expiry FROM users WHERE email = ?",
        (email,)
    )
    result = cursor.fetchone()
    
    if not result or result['reset_token'] != otp:
        db.close()
        return JSONResponse({"error": "Invalid reset request"}, status_code=400)
    
    # Hash the new password
    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
    
    # Update password and clear reset token
    cursor.execute(
        "UPDATE users SET password = ?, reset_token = NULL, reset_token_expiry = NULL WHERE email = ?",
        (hashed_password, email)
    )
    db.commit()
    db.close()
    
    return JSONResponse({"message": "Password reset successfully"})

# Example protected endpoint
@app.get("/protected")
async def protected_route(current_user: User = Depends(get_current_user)):
    return {"message": f"Hello, {current_user.name}"}

# Root endpoint (for redirect after login)
@app.get("/")
async def root():
    return {"message": "Welcome to the application"}

@app.get("/login", response_class=HTMLResponse)
def login_page():
    with open("templates/login.html", "r") as f:
        return f.read()

@app.get("/signup", response_class=HTMLResponse)
def signup_page():
    with open("templates/signup.html", "r") as f:
        return f.read()

@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page():
    with open("templates/reset_password.html", "r") as f:
        return f.read()

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    try:
        # Get JWT token from the cookie
        token = request.cookies.get("access_token")
        if not token:
            return RedirectResponse(url="/login", status_code=302)

        # Decode the token to extract user id
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        
        # Query the database for the user
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        db.close()
        
        if not row:
            return RedirectResponse(url="/login", status_code=302)
            
        user = User(id=row['id'], email=row['email'], name=row['name'], google_sub=row['google_sub'])
        return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})
            
    except jwt.InvalidTokenError:
        return RedirectResponse(url="/login", status_code=302)
    except Exception as e:
        print(f"Dashboard error: {str(e)}")
        return RedirectResponse(url="/login", status_code=302)
