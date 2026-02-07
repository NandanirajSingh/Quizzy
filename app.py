from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import os
import secrets
from functools import wraps
from flask import send_from_directory, jsonify  
from urllib.parse import unquote
import json
import logging 
from flask_cors import CORS
import time
from flask_caching import Cache
# Update your get_db_connection function to use connection pooling
from psycopg2.pool import ThreadedConnectionPool
import threading

from concurrent.futures import ThreadPoolExecutor

# Create a thread pool for background tasks
executor = ThreadPoolExecutor(max_workers=4)
# Create a connection pool
db_pool = None

def init_db_pool():
    global db_pool
    try:
        # USE THIS CONNECTION STRING FORMAT FOR NEON
        connection_string = "postgresql://neondb_owner:npg_cYsvm4VrBbK5@ep-billowing-grass-a11o6ujx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
        
        db_pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=20,
            dsn=connection_string  # Use DSN instead of individual parameters
        )
        print("Database connection pool initialized successfully with Neon")
    except Exception as e:
        print(f"Database connection pool error: {e}")
        raise

# Initialize the pool when the app starts
init_db_pool()

def get_db_connection():
    try:
        return db_pool.getconn()
    except Exception as e:
        print(f"Database connection error: {e}")
        # Fallback to direct connection with proper Neon format
        connection_string = "postgresql://neondb_owner:npg_cYsvm4VrBbK5@ep-billowing-grass-a11o6ujx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
        return psycopg2.connect(connection_string)

def return_db_connection(conn):
    try:
        db_pool.putconn(conn)
    except:
        conn.close()  # Just close if pool is not available


# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

# Create Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

from flask_compress import Compress

# Add compression to your Flask app
compress = Compress()
compress.init_app(app)

# Enable CORS
CORS(app)

# Create a directory for category pages
CATEGORIES_DIR = os.path.join('templates', 'categories')
os.makedirs(CATEGORIES_DIR, exist_ok=True)


app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutes
cache = Cache(app)

# ===== Google OAuth Configuration =====
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
    },
    authorize_params={
        'access_type': 'offline',
        'prompt': 'select_account'
    }
)


# Make sure this route doesn't already exist
@app.route('/api/create-category-page', methods=['POST'])
def create_category_page_endpoint():
    try:
        data = request.get_json()
        category_name = data.get('category_name')
        
        if not category_name:
            return jsonify({"error": "Category name is required"}), 400
        
        # Return success immediately and create page in background
        executor.submit(create_category_page_background, category_name)
        
        return jsonify({"message": "Category page creation started", "filename": f"{category_name.lower().replace(' ', '_')}.html"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def create_category_page_background(category_name):
    try:
        # Generate a unique cache busting parameter
        cache_buster = int(time.time())
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{category_name} - Quizzy</title>
    <link rel="stylesheet" href="/static/styles.css?v={cache_buster}">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="{{{{ url_for('static', filename='styles.css') }}}}?v={{{{ cache_buster }}}}">
</head>
<body class="category-page">
    <div class="main">
        <nav class="navbar" id="nav">
            <div class="logo">
                <img src="/static/logo1.png" alt="" height="45px" width="45px" style="border-radius: 50%;">
                <h1>Quizzy</h1>
            </div>
            <div class="links">
                <a href="/adminhome"><p>Home</p></a>
                <a href="/admindashboard"><p>Dashboard</p></a>
                <a href="{{ url_for('gettoknowus') }}">
                <p>About Us</p>
            </a>
            </div>
            <button class="button2" onclick="ExpandNav()">
                <i class="fa-solid fa-bars" id="menubar"></i>
            </button>
        </nav>

        <section>
            <div class="category-content">
                <div class="category-header">
                    <h2>{category_name}</h2>
                    <p>Manage quizzes and content for this category</p>
                </div>
                
                <div class="quizzes-container">
                    <div class="quizzes-header">
                        <h2>Quizzes in {category_name}</h2>
                        <button id="addQuizBtn" class="btn-primary" onclick="location.href='/createquiz'">
                            <i class="fas fa-plus"></i> Add New Quiz
                        </button>
                    </div>
                    
                    <div class="quizzes-grid" id="quizzesList">
                        <div class="loading-quizzes">
                            <i class="fas fa-spinner fa-spin"></i> Loading quizzes...
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <footer>
            <p>© 2025 Quizzy. All rights reserved.</p>
        </footer>
    </div>

    <!-- Modals -->
    <div class="modalscreen" id="deleteModal" style="display: none;">
        <div class="categorymodal">
            <div class="up"><b>Delete Quiz</b></div>
            <div class="center">
                <p>Are you sure you want to delete this quiz?</p>
                <p id="quizToDeleteName" style="font-weight: bold; margin-top: 10px;"></p>
            </div>
            <div class="down">
                <button type="button" onclick="hideDeleteModal()">Cancel</button>
                <button type="button" id="confirmDeleteQuizBtn">Delete</button>
            </div>
        </div>
    </div>

    <div class="modalscreen" id="editImageModal" style="display: none;">
        <form id="imageForm">
            <div class="categorymodal">
                <div class="up"><b>Edit Quiz Image</b></div>
                <div class="center">
                    Image URL: <input type="url" id="quizImageUrlInput" placeholder="https://example.com/image.jpg">
                </div>
                <div class="down">
                    <button type="button" onclick="hideImageModal()">Cancel</button>
                    <input type="submit" value="Save">
                </div>
            </div>
        </form>
    </div>

    <script>
     //navbar expansion
    function ExpandNav() {{
        const nav = document.getElementById("nav");
        nav.classList.toggle('expanded');
        
        // Toggle between hamburger and close icon
        const menuIcon = document.getElementById("menubar");
        if (nav.classList.contains('expanded')) {{
            menuIcon.classList.remove('fa-bars');
            menuIcon.classList.add('fa-times');
        }} else {{
            menuIcon.classList.remove('fa-times');
            menuIcon.classList.add('fa-bars');
        }}
    }}
    
    // Close menu when clicking outside
    document.addEventListener('click', function(event) {{
        const nav = document.getElementById("nav");
        const button = document.querySelector('.button2');
        
        // Check if the click is outside the nav and button
        if (!nav.contains(event.target) && !button.contains(event.target) && nav.classList.contains('expanded')) {{
            nav.classList.remove('expanded');
            const menuIcon = document.getElementById("menubar");
            menuIcon.classList.remove('fa-times');
            menuIcon.classList.add('fa-bars');
        }}
    }});
    
    // Handle window resize
    window.addEventListener('resize', function() {{
        const nav = document.getElementById("nav");
        if (window.innerWidth > 1000 && nav.classList.contains('expanded')) {{
            nav.classList.remove("expanded");
            const menuIcon = document.getElementById("menubar");
            menuIcon.classList.remove('fa-times');
            menuIcon.classList.add('fa-bars');
        }}
    }});
    
    let currentQuizToDelete = null;
    let currentQuizToEdit = null;

    function showDeleteQuizModal(quizId, quizTitle) {{
        currentQuizToDelete = quizId;
        document.getElementById("quizToDeleteName").textContent = quizTitle;
        document.getElementById("deleteModal").style.display = 'flex';
    }}

    function hideDeleteModal() {{
        document.getElementById("deleteModal").style.display = 'none';
        currentQuizToDelete = null;
    }}

    function showImageModal(quizId) {{
        currentQuizToEdit = quizId;
        document.getElementById("editImageModal").style.display = 'flex';
        document.getElementById("quizImageUrlInput").value = '';
    }}

    function hideImageModal() {{
        document.getElementById("editImageModal").style.display = 'none';
        document.getElementById("quizImageUrlInput").value = '';
        currentQuizToEdit = null;
    }}

    async function loadQuizzes() {{
        const quizzesList = document.getElementById('quizzesList');
        const categoryName = '{category_name}';
        
        try {{
            quizzesList.innerHTML = `
                <div class="loading-quizzes">
                    <i class="fas fa-spinner fa-spin"></i> Loading quizzes...
                </div>
            `;
            
            const response = await fetch('/api/categories/' + encodeURIComponent(categoryName) + '/quizzes', {{
                credentials: 'include'
            }});
            
            if (!response.ok) {{
                throw new Error('Server returned ' + response.status);
            }}
            
            const quizzes = await response.json();
            quizzesList.innerHTML = '';
            
            if (quizzes.length === 0) {{
                quizzesList.innerHTML = `
                    <div class="empty-quizzes">
                        <i class="fas fa-inbox" style="font-size: 3rem; color: #6c757d; margin-bottom: 1rem;"></i>
                        <p>No quizzes yet</p>
                        <small>Get started by creating your first quiz</small>
                    </div>
                `;
                return;
            }}
            
            quizzes.forEach(quiz => {{
                const difficultyClass = 'difficulty-' + quiz.difficulty;
                const quizCard = document.createElement('div');
                quizCard.className = 'quiz-card';
                quizCard.dataset.quizId = quiz.id;
                
                quizCard.innerHTML = `
                    <div class="quiz-card-content">
                        <h3>${{quiz.title}}</h3>
                        <p>${{quiz.description || 'No description'}}</p>
                        <div class="quiz-meta">
                            <span class="quiz-difficulty ${{difficultyClass}}">${{quiz.difficulty}}</span>
                            <span class="quiz-questions">${{quiz.num_questions}} questions</span>
                        </div>
                    </div>
                    <div class="quiz-actions">
                        <button class="quiz-action-btn edit-quiz" title="Edit Quiz Image">
                            <i class="fas fa-image"></i>
                        </button>
                        <button class="quiz-action-btn delete-quiz" title="Delete Quiz">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                `;
                
                if (quiz.image_url) {{
                    quizCard.style.backgroundImage = 'url(' + quiz.image_url + ')';
                    quizCard.style.backgroundSize = 'cover';
                    quizCard.style.backgroundPosition = 'center';
                    quizCard.classList.add("with-image");
                }}
                
                quizCard.querySelector('.delete-quiz').addEventListener('click', (e) => {{
                    e.stopPropagation();
                    showDeleteQuizModal(quiz.id, quiz.title);
                }});
                
                quizCard.querySelector('.edit-quiz').addEventListener('click', (e) => {{
                    e.stopPropagation();
                    showImageModal(quiz.id);
                }});
                
                quizzesList.appendChild(quizCard);
            }});
            
        }} catch (error) {{
            console.error('Error loading quizzes:', error);
            quizzesList.innerHTML = '<div class="error-message">Failed to load quizzes</div>';
        }}
    }}

    async function deleteQuiz() {{
        if (!currentQuizToDelete) return;
        
        try {{
            const deleteBtn = document.getElementById("confirmDeleteQuizBtn");
            deleteBtn.disabled = true;
            deleteBtn.textContent = "Deleting...";
            
            const response = await fetch('/api/quizzes/' + currentQuizToDelete, {{
                method: 'DELETE'
            }});
            
            if (response.ok) {{
                const quizCard = document.querySelector('.quiz-card[data-quiz-id="' + currentQuizToDelete + '"]');
                if (quizCard) quizCard.remove();
                hideDeleteModal();
                
                const quizzesList = document.getElementById('quizzesList');
                if (quizzesList.children.length === 0) {{
                    quizzesList.innerHTML = `
                        <div class="empty-quizzes">
                            <i class="fas fa-inbox"></i>
                            <p>No quizzes yet</p>
                            <small>Get started by creating your first quiz</small>
                        </div>
                    `;
                }}
            }} else {{
                alert('Failed to delete quiz');
            }}
        }} catch (error) {{
            console.error('Error deleting quiz:', error);
            alert('An error occurred while deleting the quiz');
        }} finally {{
            const deleteBtn = document.getElementById("confirmDeleteQuizBtn");
            if (deleteBtn) {{
                deleteBtn.disabled = false;
                deleteBtn.textContent = "Delete";
            }}
        }}
    }}

    async function handleImageSubmit(e) {{
        e.preventDefault();
        const imageUrlInput = document.getElementById("quizImageUrlInput");
        const imageUrl = imageUrlInput.value.trim();
        
        if (!imageUrl || !currentQuizToEdit) {{
            hideImageModal();
            return;
        }}
        
        try {{
            const saveBtn = document.querySelector("#imageForm [type='submit']");
            saveBtn.disabled = true;
            saveBtn.value = "Saving...";
            
            const response = await fetch('/api/quizzes/' + currentQuizToEdit + '/image', {{
                method: 'PUT',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ image_url: imageUrl }})
            }});
            
            if (response.ok) {{
                const quizCard = document.querySelector('.quiz-card[data-quiz-id="' + currentQuizToEdit + '"]');
                if (quizCard) {{
                    quizCard.style.backgroundImage = 'url(' + imageUrl + ')';
                    quizCard.style.backgroundSize = 'cover';
                    quizCard.style.backgroundPosition = 'center';
                    quizCard.classList.add("with-image");
                }}
                alert('Quiz image updated successfully!');
                hideImageModal();
            }} else {{
                throw new Error('Failed to update image');
            }}
        }} catch (error) {{
            console.error("Error updating image:", error);
            alert("Failed to update image");
        }} finally {{
            const saveBtn = document.querySelector("#imageForm [type='submit']");
            if (saveBtn) {{
                saveBtn.disabled = false;
                saveBtn.value = "Save";
            }}
        }}
    }}

    document.addEventListener('DOMContentLoaded', function() {{
        loadQuizzes();
        document.getElementById("confirmDeleteQuizBtn").addEventListener("click", deleteQuiz);
        document.getElementById("imageForm").addEventListener("submit", handleImageSubmit);
    }});
    </script>
</body>
</html>"""
        
        filename = f"{category_name.lower().replace(' ', '_')}.html"
        filepath = os.path.join(CATEGORIES_DIR, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"Category page for {category_name} created successfully")        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Add this function to pre-warm cache on startup
# def pre_warm_cache():
#     try:
#         with app.app_context():
#             # Pre-warm categories cache for admin users
#             conn = get_db_connection()
#             cur = conn.cursor()
#             cur.execute("SELECT DISTINCT created_by FROM categories LIMIT 10")
#             users = [row[0] for row in cur.fetchall()]
            
#             for user in users:
#                 # Simulate a request to cache categories for each user
#                 session['email'] = user
#                 get_categories()
            
#             cur.close()
#             conn.close()
#             logger.info("Cache pre-warming completed")
#     except Exception as e:
#         logger.error(f"Cache pre-warming failed: {e}")

# # Call this function when your app starts
# pre_warm_cache()

# Route to serve category pages
@app.route('/categories/<category_name>')
def serve_category_page(category_name):
    try:
        category_name = unquote(category_name)
        filename = f"{category_name.lower().replace(' ', '_')}.html"
        return send_from_directory(CATEGORIES_DIR, filename)
    except:
        return "Category page not found", 404

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'email' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ===== Routes =====
@app.route('/')
def home():
    return render_template('UserHome.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    message = ""
    google_user = session.pop('google_temp_user', None) if request.method == "GET" else None
    
    if request.method == "POST":
        fname = request.form["FNAME"]
        lname = request.form["LNAME"]
        email = request.form["EMAIL"]
        password = request.form["PASSWORD"]
        confirm_password = request.form["CONFIRM_PASSWORD"]

        if password != confirm_password:
            return render_template("registration.html", 
                               message="Passwords do not match!",
                               google_user={'fname': fname, 'lname': lname, 'email': email})

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                return render_template("registration.html", 
                                    message="Email already registered!",
                                    google_user={'fname': fname, 'lname': lname, 'email': email})

            hashed_password = generate_password_hash(password)
            cur.execute(
                "INSERT INTO users (fname, lname, email, password) VALUES (%s, %s, %s, %s)",
                (fname, lname, email, hashed_password)
            )
            conn.commit()
            return redirect(url_for("login", message="Registration successful! Please login"))
        finally:
            cur.close()
            conn.close()

    return render_template("registration.html", message=message, google_user=google_user)

@app.route("/login", methods=["GET", "POST"])
def login():
    message = request.args.get('message', '')
    prefilled_email = request.args.get('prefilled_email', '')
    
    if not prefilled_email and 'google_prefill_email' in session:
        prefilled_email = session['google_prefill_email']
        session.pop('google_prefill_email', None)
    
    if request.method == "POST":
        email = request.form["EMAIL"]
        password = request.form["PASSWORD"]

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT password FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            
            if not user:
                return render_template("login.html", 
                                     message="User does not exist!", 
                                     prefilled_email=email)
            
            if not check_password_hash(user[0], password):
                return render_template("login.html", 
                                     message="Incorrect password!", 
                                     prefilled_email=email)
            
            session["email"] = email
            session["is_admin"] = (email == "nandnirajsingh2005@gmail.com")
            
            # Redirect based on admin status
            if session["is_admin"]:
                return redirect(url_for("adminhome"))
            else:
                return redirect(url_for("not_admin"))
        finally:
            cur.close()
            conn.close()

    return render_template("login.html", 
                         message=message, 
                         prefilled_email=prefilled_email)


@app.route('/not-admin')
def not_admin():
    if "email" not in session:
        return redirect(url_for("login"))
    return render_template('not_admin.html')

@app.route('/api/refresh-category-pages', methods=['POST'])
@login_required
def refresh_category_pages():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM categories WHERE created_by = %s", (session['email'],))
        categories = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        
        cache_buster = int(time.time())
        for category_name in categories:
            html_content = f"""<!DOCTYPE html><html><head><title>{category_name}</title></head><body></body></html>"""
            filename = f"{category_name.lower().replace(' ', '_')}.html"
            filepath = os.path.join(CATEGORIES_DIR, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
        
        return jsonify({"message": f"Refreshed {len(categories)} category pages"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.context_processor
def inject_cache_buster():
    return {'cache_buster': int(time.time())}

@app.route("/dashboard")
def dashboard():
    if "email" not in session:
        return redirect(url_for("login"))
    
    if session.get("is_admin"):
        return redirect(url_for("adminhome"))
    else:
        return redirect(url_for("not_admin"))

@app.route('/register/google')
def google_register():
    session['oauth_nonce'] = secrets.token_urlsafe(16)
    redirect_uri = url_for('google_register_callback', _external=True)
    return google.authorize_redirect(redirect_uri, nonce=session['oauth_nonce'])

@app.route('/register/google/callback')
def google_register_callback():
    try:
        token = google.authorize_access_token()
        if not token:
            return redirect(url_for('register', message="Google sign up failed"))

        userinfo = google.parse_id_token(token, nonce=session.pop('oauth_nonce', None))
        if not userinfo.get('email'):
            return redirect(url_for('register', message="No email from Google"))

        session['google_temp_user'] = {
            'fname': userinfo.get('given_name', ''),
            'lname': userinfo.get('family_name', ''),
            'email': userinfo['email']
        }
        return redirect(url_for('register'))
        
    except Exception as e:
        return redirect(url_for('register', message=f"Google sign up failed: {str(e)}"))
    
@app.route('/login/google')
def google_login():
    session['oauth_nonce'] = secrets.token_urlsafe(16)
    redirect_uri = url_for('google_login_callback', _external=True)
    return google.authorize_redirect(redirect_uri, nonce=session['oauth_nonce'])

@app.route('/login/google/callback')
def google_login_callback():
    try:
        token = google.authorize_access_token()
        if not token:
            return redirect(url_for('login', message="Google login failed"))

        userinfo = google.parse_id_token(token, nonce=session.pop('oauth_nonce', None))
        if not userinfo.get('email'):
            return redirect(url_for('login', message="No email from Google"))

        session['google_prefill_email'] = userinfo['email']
        return redirect(url_for('login', prefilled_email=userinfo['email']))
            
    except Exception as e:
        return redirect(url_for('login', message=f"Google login failed: {str(e)}"))
    

@app.route("/logout")
def logout():
    session.pop("email", None)
    return redirect(url_for("login"))

@app.route('/userhome')
def userhome():
    return render_template('UserHome.html')

@app.route('/adminhome')
def adminhome():
    return render_template('AdminHome.html')

@app.route('/admindashboard')
def admindashboard():
    return render_template('AdminDashboard.html')

@app.route('/userdashboard')
def userdashboard():
    return render_template('UserDashboard.html')

@app.route('/joinus')
def joinus():
    return render_template('Join.html')

@app.route('/createquiz')
def createquiz():
    cache_buster = int(time.time())
    return render_template('createquiz.html', cache_buster=cache_buster)

@app.route('/gettoknowus')
def gettoknowus():
    return render_template('Gettoknowus.html')

# GET all categories - WITH CACHING for admin
@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    conn = None
    cur = None
    try:
        # Clear cache for this user to ensure fresh data
        cache_key = f"categories_{session['email']}"
        cache.delete(cache_key)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT name, image_url 
            FROM categories 
            WHERE created_by = %s 
            ORDER BY name
            LIMIT 50
            """, (session['email'],))
        categories = [{'name': row[0], 'image_url': row[1]} for row in cur.fetchall()]
        return jsonify(categories)
    except Exception as e:
        logger.error(f"Error fetching categories: {e}")
        return jsonify([])  # Return empty array instead of error
    finally:
        if cur:
            cur.close()
        if conn:
            return_db_connection(conn)

# POST new category
@app.route('/api/categories', methods=['POST'])
@login_required
def create_category():
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Category name is required'}), 400
        
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Clear cache for this user
        cache_key = f"categories_{session['email']}"
        cache.delete(cache_key)
        
        cur.execute("SELECT 1 FROM categories WHERE name = %s AND created_by = %s", 
                   (data['name'], session['email']))
        if cur.fetchone():
            return jsonify({'error': 'Category already exists'}), 400
            
        cur.execute(
            "INSERT INTO categories (name, created_by) VALUES (%s, %s) RETURNING name",
            (data['name'], session['email'])
        )
        conn.commit()
        
        # Clear cache again after successful creation
        cache.delete(cache_key)
        
        return jsonify({'name': cur.fetchone()[0]}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# DELETE category
@app.route('/api/categories/<name>', methods=['DELETE'])
@login_required
def delete_category(name):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM categories WHERE name = %s AND created_by = %s RETURNING name", 
                   (name, session['email']))
        if cur.rowcount == 0:
            return jsonify({'error': 'Category not found'}), 404
            
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# PUT update category image
@app.route('/api/categories/<name>/image', methods=['PUT'])
@login_required
def update_category_image(name):
    data = request.get_json()
    if not data or not data.get('image_url'):
        return jsonify({'error': 'Image URL is required'}), 400
        
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE categories SET image_url = %s WHERE name = %s AND created_by = %s RETURNING name",
            (data['image_url'], name, session['email'])
        )
        if cur.rowcount == 0:
            return jsonify({'error': 'Category not found'}), 404
            
        conn.commit()
        return jsonify({'name': cur.fetchone()[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()
        
# GET quizzes for a category - UPDATED for new structure with caching
@app.route('/api/categories/<category_name>/quizzes', methods=['GET'])
@login_required
def get_quizzes(category_name):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # First verify the category belongs to the current user
        cur.execute("SELECT name FROM categories WHERE name = %s AND created_by = %s", 
                   (category_name, session['email']))
        if not cur.fetchone():
            return jsonify({'error': 'Category not found or access denied'}), 404
        
        # Get quizzes for this category
        cur.execute("""
            SELECT q.id, q.title, q.description, q.difficulty, q.created_at, q.image_url,
                   COUNT(qq.id) as num_questions
            FROM quizzes q
            LEFT JOIN quiz_questions qq ON q.id = qq.quiz_id
            WHERE q.category = %s AND q.created_by = %s 
            GROUP BY q.id
            ORDER BY q.created_at DESC
        """, (category_name, session['email']))
        
        rows = cur.fetchall()
        
        quizzes = []
        for row in rows:
            quizzes.append({
                'id': row[0],
                'title': row[1],
                'description': row[2],
                'difficulty': row[3],
                'created_at': row[4].isoformat() if row[4] else None,
                'image_url': row[5],
                'num_questions': row[6]
            })
            
        return jsonify(quizzes)
    except Exception as e:
        logger.error(f"Error retrieving quizzes: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            return_db_connection(conn)

# POST new quiz - UPDATED for new structure
@app.route('/api/quizzes', methods=['POST'])
@login_required
def create_quiz():
    try:
        data = request.get_json()
        
        if data is None:
            return jsonify({'error': 'Invalid JSON data'}), 400
            
        if not data.get('title') or not data.get('category'):
            return jsonify({'error': 'Title and category are required'}), 400
            
        if not data.get('questions') or len(data['questions']) == 0:
            return jsonify({'error': 'At least one question is required'}), 400
            
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # First verify the category belongs to the current user
            cur.execute("SELECT name FROM categories WHERE name = %s AND created_by = %s", 
                       (data['category'], session['email']))
            if not cur.fetchone():
                return jsonify({'error': 'Category not found or access denied'}), 400
            
            # Then create the quiz
            cur.execute(
                "INSERT INTO quizzes (title, description, category, difficulty, created_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (data['title'], data.get('description', ''), data['category'], data.get('difficulty', 'medium'), session['email'])
            )
            quiz_id = cur.fetchone()[0]
            
            # Then insert questions into quiz_questions table
            for question in data['questions']:
                # Ensure options is properly formatted as JSON
                options = question.get('options', [])
                if not isinstance(options, list):
                    options = [options] if options else []
                
                cur.execute(
                    "INSERT INTO quiz_questions (quiz_id, question, options, correct_answer) VALUES (%s, %s, %s, %s)",
                    (quiz_id, question['question'], json.dumps(options), question['correctAnswer'])
                )
            
            conn.commit()
            return jsonify({'id': quiz_id, 'message': 'Quiz created successfully'}), 201
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error in create_quiz: {e}")
            return jsonify({'error': f'Database error occurred: {str(e)}'}), 500
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.error(f"Error in create_quiz: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

# DELETE quiz
@app.route('/api/quizzes/<int:quiz_id>', methods=['DELETE'])
@login_required
def delete_quiz(quiz_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM quizzes WHERE id = %s AND created_by = %s RETURNING id", 
                   (quiz_id, session['email']))
        if cur.rowcount == 0:
            return jsonify({'error': 'Quiz not found'}), 404
            
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# PUT update quiz image
@app.route('/api/quizzes/<int:quiz_id>/image', methods=['PUT'])
@login_required
def update_quiz_image(quiz_id):
    data = request.get_json()
    if not data or not data.get('image_url'):
        return jsonify({'error': 'Image URL is required'}), 400
        
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM quizzes WHERE id = %s AND created_by = %s", 
                   (quiz_id, session['email']))
        if not cur.fetchone():
            return jsonify({'error': 'Quiz not found'}), 404
            
        cur.execute(
            "UPDATE quizzes SET image_url = %s WHERE id = %s RETURNING id",
            (data['image_url'], quiz_id)
        )
        
        conn.commit()
        return jsonify({'success': True, 'quiz_id': quiz_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/session-heartbeat', methods=['POST'])
def session_heartbeat():
    # Just touching the session keeps it alive
    if 'email' in session:
        session.modified = True  # Mark session as modified to keep it alive
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'No session'}), 401


@app.before_request
def check_session_validity():
    # Skip session check for static files, login/register pages, and public API endpoints
    if (request.path.startswith('/static/') or 
        request.path in ['/login', '/register', '/'] or
        request.path.startswith('/api/user/')):
        return
    
    # Check if user is trying to access protected API endpoints without valid session
    if request.path.startswith('/api/') and 'email' not in session:
        return jsonify({'error': 'Session expired'}), 401
@app.after_request
def add_header(response):
    # Cache static assets for 1 hour
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    else:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
    return response


from flask_caching import Cache

# Configure caching
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutes
cache = Cache(app)

# GET all categories for users (no authentication required) - WITH CACHING
@app.route('/api/user/categories', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def get_categories_for_users():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get all categories available to users
        cur.execute("""
            SELECT DISTINCT name, COALESCE(image_url, '') as image_url 
            FROM categories 
            WHERE name IS NOT NULL AND name != ''
            ORDER BY name
            LIMIT 100
            """)
        
        categories = []
        for row in cur.fetchall():
            categories.append({
                'name': row[0], 
                'image_url': row[1] if row[1] else None
            })
        
        logger.info(f"Returning {len(categories)} categories for user view")
        return jsonify(categories)
        
    except Exception as e:
        logger.error(f"Error fetching categories for users: {e}")
        return jsonify([])
    finally:
        if cur:
            cur.close()
        if conn:
            return_db_connection(conn)

# GET quizzes for a category for users - FURTHER OPTIMIZED
@app.route('/api/user/categories/<category_name>/quizzes', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def get_quizzes_for_users(category_name):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Use a materialized view for even better performance
        # First check if the materialized view exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'quiz_summary'
            );
        """)
        
        view_exists = cur.fetchone()[0]
        
        if view_exists:
            # Use the materialized view
            cur.execute("""
                SELECT id, title, description, difficulty, image_url, num_questions
                FROM quiz_summary
                WHERE category = %s
                ORDER BY created_at DESC
                LIMIT 50
            """, (category_name,))
        else:
            # Use the regular query
            cur.execute("""
                SELECT q.id, q.title, q.description, q.difficulty, q.image_url,
                       (SELECT COUNT(*) FROM quiz_questions qq WHERE qq.quiz_id = q.id) as num_questions
                FROM quizzes q
                WHERE q.category = %s
                ORDER BY q.created_at DESC
                LIMIT 50
            """, (category_name,))
        
        quizzes = []
        for row in cur.fetchall():
            quizzes.append({
                'id': row[0],
                'title': row[1],
                'description': row[2],
                'difficulty': row[3],
                'image_url': row[4],
                'num_questions': row[5]
            })
            
        return jsonify(quizzes)
    except Exception as e:
        logger.error(f"Error retrieving quizzes for users: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            return_db_connection(conn)

# GET a specific quiz with questions for users to take - OPTIMIZED
@app.route('/api/user/quizzes/<int:quiz_id>', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def get_quiz_for_user(quiz_id):
    logger.info(f"Loading quiz {quiz_id} for user")
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get quiz details
        cur.execute("""
            SELECT id, title, description, category, difficulty, image_url
            FROM quizzes 
            WHERE id = %s
        """, (quiz_id,))
        
        quiz_row = cur.fetchone()
        if not quiz_row:
            logger.warning(f"Quiz {quiz_id} not found")
            return jsonify({'error': 'Quiz not found'}), 404
            
        # Get questions for this quiz
        cur.execute("""
            SELECT id, question, options, correct_answer
            FROM quiz_questions 
            WHERE quiz_id = %s
            ORDER BY id
        """, (quiz_id,))
        
        questions = []
        question_rows = cur.fetchall()
        
        for row in question_rows:
            options_data = row[2]
            options = []
            
            # Handle both list and JSON string formats
            if isinstance(options_data, list):
                # Already a Python list
                options = options_data
            else:
                # Try to parse as JSON string
                try:
                    options = json.loads(options_data)
                except (json.JSONDecodeError, TypeError):
                    # If parsing fails, use default options
                    options = ["Option 1", "Option 2", "Option 3", "Option 4"]
            
            questions.append({
                'id': row[0],
                'question': row[1],
                'options': options,
                'correct_answer': row[3]
            })
            
        quiz = {
            'id': quiz_row[0],
            'title': quiz_row[1],
            'description': quiz_row[2],
            'category': quiz_row[3],
            'difficulty': quiz_row[4],
            'image_url': quiz_row[5],
            'questions': questions
        }
        
        return jsonify(quiz)
        
    except Exception as e:
        logger.error(f"Error retrieving quiz for user: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# POST to submit quiz answers and get results
@app.route('/api/user/quizzes/<int:quiz_id>/submit', methods=['POST'])
def submit_quiz(quiz_id):
    try:
        data = request.get_json()
        
        if data is None or 'answers' not in data:
            return jsonify({'error': 'Answers are required'}), 400
            
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Get correct answers for this quiz
            cur.execute("""
                SELECT id, correct_answer
                FROM quiz_questions 
                WHERE quiz_id = %s
                ORDER BY id
            """, (quiz_id,))
            
            correct_answers = {}
            question_rows = cur.fetchall()
            for row in question_rows:
                correct_answers[row[0]] = row[1]
            
            # Calculate score
            user_answers = data['answers']
            score = 0
            total_questions = len(correct_answers)
            results = {}
            
            for question_id, user_answer in user_answers.items():
                question_id = int(question_id)
                if question_id in correct_answers and user_answer == correct_answers[question_id]:
                    score += 1
                    results[question_id] = {'correct': True, 'user_answer': user_answer}
                else:
                    results[question_id] = {
                        'correct': False, 
                        'user_answer': user_answer, 
                        'correct_answer': correct_answers.get(question_id)
                    }
            
            # Save quiz attempt if user is logged in
            if 'email' in session:
                time_spent = data.get('time_spent', 0)
                cur.execute(
                    "INSERT INTO quiz_attempts (user_email, quiz_id, score, total_questions, time_spent) VALUES (%s, %s, %s, %s, %s)",
                    (session['email'], quiz_id, score, total_questions, time_spent)
                )
                conn.commit()
            
            return jsonify({
                'score': score,
                'total_questions': total_questions,
                'percentage': round((score / total_questions) * 100, 2) if total_questions > 0 else 0,
                'results': results
            })
            
        except Exception as e:
            conn.rollback()
            return jsonify({'error': f'Database error occurred: {str(e)}'}), 500
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

# Route to serve user category pages
@app.route('/user/categories/<category_name>')
def serve_user_category_page(category_name):
    try:
        # No login required for viewing categories
        return render_template('user_category.html', category_name=category_name)
    except Exception as e:
        return f"Error loading category: {str(e)}", 500
    
# Route to serve user quiz page
# Route to serve user quiz page
@app.route('/user/quiz/<int:quiz_id>')
def serve_user_quiz_page(quiz_id):
    try:
        # No login required for viewing quiz details (but submission will require login)
        return render_template('user_quiz_portal.html', quiz_id=quiz_id)
    except Exception as e:
        return f"Error loading quiz: {str(e)}", 500

# Route to check and initialize database tables
@app.route('/api/check-db')
def check_database():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check if quiz_attempts table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'quiz_attempts'
            );
        """)
        table_exists = cur.fetchone()[0]
        
        if not table_exists:
            # Create the quiz_attempts table
            cur.execute("""
                CREATE TABLE quiz_attempts (
                    id SERIAL PRIMARY KEY,
                    user_email VARCHAR(255) NOT NULL,
                    quiz_id INTEGER NOT NULL,
                    score INTEGER NOT NULL,
                    total_questions INTEGER NOT NULL,
                    time_spent INTEGER DEFAULT 0,
                    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
                );
            """)
            conn.commit()
            return jsonify({"message": "quiz_attempts table created successfully"})
        else:
            # Check if time_spent column exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'quiz_attempts' AND column_name = 'time_spent'
                );
            """)
            column_exists = cur.fetchone()[0]
            
            if not column_exists:
                cur.execute("ALTER TABLE quiz_attempts ADD COLUMN time_spent INTEGER DEFAULT 0;")
                conn.commit()
                return jsonify({"message": "time_spent column added to quiz_attempts table"})
            
            return jsonify({"message": "quiz_attempts table exists with all required columns"})
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Debug endpoint to check user categories
@app.route('/api/debug/user-categories')
def debug_user_categories():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check what's actually in the database
        cur.execute("SELECT name, image_url FROM categories LIMIT 20")
        db_categories = cur.fetchall()
        
        # Check the user endpoint response
        user_categories = get_categories_for_users().get_json()
        
        return jsonify({
            "database_categories": [{"name": row[0], "image_url": row[1]} for row in db_categories],
            "user_endpoint_categories": user_categories,
            "user_endpoint_returns": len(user_categories) if user_categories else 0
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Debug route to list all quizzes
@app.route('/api/debug/quizzes')
def debug_quizzes():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT q.id, q.title, q.category, COUNT(qq.id) as question_count
            FROM quizzes q
            LEFT JOIN quiz_questions qq ON q.id = qq.quiz_id
            GROUP BY q.id
            ORDER BY q.id
        """)
        
        quizzes = []
        for row in cur.fetchall():
            quizzes.append({
                'id': row[0],
                'title': row[1],
                'category': row[2],
                'question_count': row[3]
            })
            
        return jsonify(quizzes)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Test route to verify API is working
@app.route('/api/test')
def test_api():
    return jsonify({"message": "API is working", "status": "success"})

# Test route to verify database connection
@app.route('/api/test-db')
def test_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        result = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"message": "Database connection successful", "result": result[0]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Debug route to check quiz questions in detail
@app.route('/api/debug/quiz/<int:quiz_id>/questions')
def debug_quiz_questions(quiz_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get quiz details
        cur.execute("SELECT id, title FROM quizzes WHERE id = %s", (quiz_id,))
        quiz = cur.fetchone()
        if not quiz:
            return jsonify({"error": "Quiz not found"}), 404
        
        # Get questions
        cur.execute("""
            SELECT id, question, options, correct_answer
            FROM quiz_questions 
            WHERE quiz_id = %s
            ORDER BY id
        """, (quiz_id,))
        
        questions = []
        question_rows = cur.fetchall()
        
        for row in question_rows:
            options_data = row[2]
            options = []
            options_error = None
            
            # Check if options is already a list (not a JSON string)
            if isinstance(options_data, list):
                options = options_data
                options_type = "Already a Python list"
            else:
                # Try to parse as JSON string
                try:
                    options = json.loads(options_data)
                    options_type = "JSON string parsed successfully"
                except json.JSONDecodeError as e:
                    options_error = f"JSON decode error: {str(e)}"
                    options_type = "Invalid JSON"
                    # Fallback to default options
                    options = ["Option 1", "Option 2", "Option 3", "Option 4"]
                except TypeError as e:
                    options_error = f"Type error: {str(e)}"
                    options_type = "Unexpected data type"
                    options = ["Option 1", "Option 2", "Option 3", "Option 4"]
            
            questions.append({
                'id': row[0],
                'question': row[1],
                'options': options,
                'options_type': options_type,
                'options_raw_type': str(type(options_data)),
                'options_raw_sample': str(options_data)[:100] + ('...' if len(str(options_data)) > 100 else ''),
                'correct_answer': row[3],
                'options_error': options_error
            })
        
        return jsonify({
            'quiz_id': quiz[0],
            'quiz_title': quiz[1],
            'questions': questions,
            'total_questions': len(questions)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Add this at the end of your app.py
@app.teardown_appcontext
def close_db_connection(exception):
    # This will be called when the app context tears down
    pass  # Our connection pool handles this automatically

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)