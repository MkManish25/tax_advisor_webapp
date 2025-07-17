from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import uuid
import shutil
from werkzeug.utils import secure_filename
import PyPDF2
import pytesseract
from pdf2image import convert_from_path
import requests
import json
import re
import ast
import tax_calculator
from datetime import datetime
from decimal import Decimal # NEW IMPORT

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# NEW: Custom JSON encoder to handle Decimal types from the database
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(CustomJSONEncoder, self).default(obj)

app = Flask(__name__)
app.json_encoder = CustomJSONEncoder # Use the custom encoder for all jsonify calls
app.secret_key = os.urandom(24)

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max

def get_db_connection():
    """Create and return a database connection"""
    try:
        connection = psycopg2.connect(os.getenv('DB_URL'))
        return connection
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

def test_db_connection():
    """Test database connectivity"""
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
            return True
        return False
    except Exception as e:
        logger.error(f"Database test failed: {e}")
        return False

@app.route('/')
def index():
    """Landing page route"""
    return render_template('index.html')

@app.route('/health')
def health_check():
    """Health check endpoint for deployment"""
    db_status = "connected" if test_db_connection() else "disconnected"
    
    return jsonify({
        'status': 'healthy',
        'phase': '1',
        'database': db_status,
        'environment': 'development' if app.debug else 'production'
    })

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return render_template('index.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({'error': 'Internal server error'}), 500

# Helper: allowed file

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Helper: mock Gemini LLM extraction (replace with real API in prod)
def extract_structured_data(text):
    """
    Use Gemini LLM to extract structured salary/tax data from text.
    Returns a dict with UserFinancials fields.
    Enhanced with error handling and logging.
    Logs extracted text and Gemini response for debugging.
    """
    import logging
    logger = logging.getLogger("gemini_extraction")
    api_key = os.getenv('GEMINI_API_KEY')
    endpoint = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'

    # Log the extracted text
    logger.info(f"Extracted text length: {len(text)}")
    logger.debug(f"Extracted text (first 500 chars): {text[:500]}")
    if not text or len(text.strip()) < 30:
        logger.warning("Extracted text is empty or too short. PDF extraction may have failed.")

    prompt = (
        """
        You are an expert financial data extractor. Analyze the following text from a salary slip or Form 16.
        First, determine if the document represents a single month's salary.
        If it is a monthly payslip, you MUST multiply the values for the fields gross_salary, basic_salary, hra_received, professional_tax, and tds by 12 to get the annual amount.
        Fields like deduction_80c, deduction_80d, and rent_paid should be assumed to be annual figures and should NOT be multiplied.
        
        Return ONLY a valid JSON object with the following keys, containing the correct annual numeric values (use 0 if a value is not found):
        - gross_salary
        - basic_salary
        - hra_received
        - rent_paid
        - deduction_80c
        - deduction_80d
        - standard_deduction
        - professional_tax
        - tds
        
        Do not include any explanation, only the final JSON object.
        Example for a monthly slip with 50,000 gross salary: {"gross_salary": 600000, ...}
        
        Text:
        """ + text.strip()[:6000] + "\n"
    )
    headers = {
        'Content-Type': 'application/json',
    }
    params = {
        'key': api_key
    }
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    try:
        logger.info("Sending request to Gemini API...")
        resp = requests.post(endpoint, headers=headers, params=params, data=json.dumps(data), timeout=30)
        logger.info(f"Gemini API status: {resp.status_code}")
        logger.debug(f"Request payload: {data}")
        resp.raise_for_status()
        result = resp.json()
        logger.debug(f"Gemini API response (raw): {result}")
        # Parse Gemini's response for JSON
        candidates = result.get('candidates', [])
        if not candidates:
            logger.error("No candidates in Gemini response.")
        else:
            content = candidates[0].get('content', {})
            parts = content.get('parts', [])
            if not parts:
                logger.error("No parts in Gemini candidate content.")
            else:
                response_text = parts[0].get('text', '')
                logger.debug(f"Gemini response text: {response_text}")
                match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if match:
                    try:
                        data_dict = json.loads(match.group(0))
                        logger.info(f"Extracted structured data: {data_dict}")
                    except Exception as e:
                        logger.warning(f"json.loads failed: {e}, trying ast.literal_eval...")
                        try:
                            data_dict = ast.literal_eval(match.group(0))
                            logger.info(f"Extracted structured data (ast): {data_dict}")
                        except Exception as e2:
                            logger.error(f"Failed to parse Gemini JSON: {e2}")
                            data_dict = None
                    if data_dict:
                        # Fill missing fields with 0
                        fields = [
                            'gross_salary', 'basic_salary', 'hra_received', 'rent_paid',
                            'deduction_80c', 'deduction_80d', 'standard_deduction',
                            'professional_tax', 'tds'
                        ]
                        for f in fields:
                            if f not in data_dict:
                                logger.warning(f"Field '{f}' missing in Gemini response. Setting to 0.")
                                data_dict[f] = 0
                        return data_dict
                else:
                    logger.error("No JSON object found in Gemini response text.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Request to Gemini API failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in Gemini extraction: {e}")
    # Fallback: return empty/defaults
    logger.warning("Falling back to default values for extracted data.")
    return {
        'gross_salary': 0,
        'basic_salary': 0,
        'hra_received': 0,
        'rent_paid': 0,
        'deduction_80c': 0,
        'deduction_80d': 0,
        'standard_deduction': 50000,
        'professional_tax': 0,
        'tds': 0,
    }

def get_user_financials(session_id):
    """Fetches user financial data from the database."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM UserFinancials WHERE session_id = %s", (session_id,))
            user_data = cur.fetchone()
            return user_data
    except Exception as e:
        logger.error(f"Error fetching user data: {e}")
        return None
    finally:
        conn.close()

def ask_gemini(prompt):
    """Generic helper function to call Gemini API and get text response."""
    api_key = os.getenv('GEMINI_API_KEY')
    endpoint = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
    headers = {'Content-Type': 'application/json'}
    params = {'key': api_key}
    data = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        resp = requests.post(endpoint, headers=headers, params=params, data=json.dumps(data), timeout=45)
        resp.raise_for_status()
        result = resp.json()
        return result['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return None

# Route: PDF upload and extraction
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        file = request.files['pdf_file']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            session_id = str(uuid.uuid4())
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{session_id}_{filename}")
            file.save(save_path)
            # Extract text from PDF
            try:
                text = ""
                # Try PyPDF2 first
                with open(save_path, 'rb') as pdf_file:
                    reader = PyPDF2.PdfReader(pdf_file)
                    for page in reader.pages:
                        text += page.extract_text() or ''
                # If text is too short, try OCR
                if len(text.strip()) < 50:
                    images = convert_from_path(save_path)
                    for img in images:
                        text += pytesseract.image_to_string(img)
                # Mock Gemini LLM extraction
                extracted = extract_structured_data(text)
                extracted['session_id'] = session_id
            except Exception as e:
                flash(f'Extraction failed: {e}', 'danger')
                os.remove(save_path)
                return redirect(request.url)
            # Delete file after extraction
            try:
                os.remove(save_path)
            except Exception:
                pass
            # Render form with extracted data
            # Ensure tax_regime is initialized for the form
            if 'tax_regime' not in extracted:
                extracted['tax_regime'] = 'new'
            return render_template('form.html', data=extracted)
        else:
            flash('Invalid file type. Only PDF allowed.', 'danger')
            return redirect(request.url)
    # GET: show upload form
    return render_template('upload.html')

# Route: Data review form (optional direct access)
@app.route('/form', methods=['GET'])
def form():
    # For demo, show empty form
    empty = {
        'gross_salary': '',
        'basic_salary': '',
        'hra_received': '',
        'rent_paid': '',
        'deduction_80c': '',
        'deduction_80d': '',
        'standard_deduction': '50000',
        'professional_tax': '',
        'tds': '',
        'session_id': str(uuid.uuid4()),
        'tax_regime': 'new',
    }
    return render_template('form.html', data=empty)

@app.route('/calculate', methods=['POST'])
def calculate():
    """
    Receives form data, saves to DB, calculates tax, and shows results.
    """
    form_data = request.form.to_dict()
    session_id = form_data.get('session_id')

    # Save to DB
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                # Upsert UserFinancials
                cur.execute("""
                    INSERT INTO UserFinancials (session_id, gross_salary, basic_salary, hra_received, rent_paid, deduction_80c, deduction_80d, standard_deduction, professional_tax, tds)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        gross_salary = EXCLUDED.gross_salary,
                        basic_salary = EXCLUDED.basic_salary,
                        hra_received = EXCLUDED.hra_received,
                        rent_paid = EXCLUDED.rent_paid,
                        deduction_80c = EXCLUDED.deduction_80c,
                        deduction_80d = EXCLUDED.deduction_80d,
                        standard_deduction = EXCLUDED.standard_deduction,
                        professional_tax = EXCLUDED.professional_tax,
                        tds = EXCLUDED.tds;
                """, (
                    session_id, form_data.get('gross_salary'), form_data.get('basic_salary'), form_data.get('hra_received'),
                    form_data.get('rent_paid'), form_data.get('deduction_80c'), form_data.get('deduction_80d'),
                    form_data.get('standard_deduction'), form_data.get('professional_tax'), form_data.get('tds')
                ))
            conn.commit()
        except Exception as e:
            logger.error(f"DB Error on save: {e}")
        finally:
            conn.close()

    # Calculate Tax
    net_old = tax_calculator.get_net_taxable_income_old(form_data)
    net_new = tax_calculator.get_net_taxable_income_new(form_data)
    tax_old = tax_calculator.calculate_old_regime_tax(net_old)
    tax_new = tax_calculator.calculate_new_regime_tax(net_new)

    results_data = {
        'session_id': session_id,
        'tax_old_regime': tax_old,
        'tax_new_regime': tax_new,
        'selected_regime': form_data.get('tax_regime')
    }

    return render_template('results.html', results=results_data)

@app.route('/advisor/<session_id>', methods=['GET', 'POST'])
def advisor(session_id):
    user_data = get_user_financials(session_id)
    if not user_data:
        flash("Session not found. Please start over.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Step 2: Generate suggestions
        question = request.form.get('question')
        answer = request.form.get('answer')

        suggestion_prompt = f"""
            You are an expert tax advisor in India. Based on the user's financial data, your initial question, and their answer, provide a list of 3-5 personalized, actionable tax-saving suggestions. Format the response as a simple, unformatted list separated by newlines, with each suggestion starting with a hyphen.

            User's Financial Data: {json.dumps(user_data, indent=2, cls=CustomJSONEncoder)}
            Your Initial Question: "{question}"
            User's Answer: "{answer}"
        """
        suggestions_text = ask_gemini(suggestion_prompt)
        suggestions = suggestions_text.strip().split('\n') if suggestions_text else ["Sorry, I couldn't generate suggestions at this time."]
        
        # Log conversation
        log_entry = {
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "initial_question": question,
            "user_answer": answer,
            "final_suggestions": suggestions_text
        }
        try:
            with open("ai_conversation_log.json", "a") as f:
                f.write(json.dumps(log_entry, cls=CustomJSONEncoder) + "\n")
        except Exception as e:
            logger.error(f"Failed to write to conversation log: {e}")

        return render_template('ask.html', suggestions=suggestions, question=question, answer=answer)

    # Step 1: Generate question
    question_prompt = f"""
        You are a friendly financial advisor. Based on the user's summarized annual financial data, ask one single, concise, and thought-provoking question to better understand their financial goals or habits. The question should help you give better tax advice. Ask about their goals or habits, not for more numbers. Return ONLY the question.
        
        Example: If deduction_80c is 0, you might ask: "Are you currently exploring any tax-saving investment options like ELSS or PPF?"
        
        User's Data: {json.dumps(user_data, indent=2, cls=CustomJSONEncoder)}
    """
    question = ask_gemini(question_prompt) or "What is your primary goal for tax-saving this year?"
    return render_template('ask.html', question=question.strip(), session_id=session_id)

if __name__ == '__main__':
    # Validate environment variables
    required_vars = ['DB_URL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        logger.error("Please check your .env file")
        exit(1)
    
    # Test database connection on startup
    if test_db_connection():
        logger.info("Database connection successful")
    else:
        logger.warning("Database connection failed - check your DB_URL")
    
    app.run(debug=True, host='0.0.0.0', port=5000) 