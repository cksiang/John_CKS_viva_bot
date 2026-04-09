import os
import telebot
import google.generativeai as genai
import fitz  # PyMuPDF
import io
from supabase import create_client, Client
from flask import Flask
from threading import Thread
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import time

# --- 1. CONFIGURATION ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECEIVER_EMAIL = os.environ.get('RECEIVER_EMAIL')
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL')

# Initialize Clients
bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Flask server for Render/Cron-job pings
app = Flask(__name__)
@app.route('/')
def home(): 
    return "Bot is Running"

def run_flask():
    # Render uses the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def self_ping():
    while True:
        try:
            if RENDER_EXTERNAL_URL:
                requests.get(RENDER_EXTERNAL_URL)
                print("Self-ping successful")
            else:
                print("RENDER_EXTERNAL_URL not set")
        except Exception as e:
            print(f"Self-ping error: {e}")
        time.sleep(600)  # 10 minutes

# --- 2. EMAIL UTILITY ---
def send_email(subject, body):
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Email Error: {e}")
        return False

# --- 3. BOT LOGIC ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Welcome! Please upload your Thesis chapter (PDF or Text). I will analyze it, generate defense questions, and email them to you.")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    filename = message.document.file_name.lower()
    content = ""

    bot.reply_to(message, "📄 Reading your file... please wait.")

    try:
        # Check if file is PDF
        if filename.endswith('.pdf'):
            # Use PyMuPDF to extract text from the PDF stream
            with fitz.open(stream=downloaded_file, filetype="pdf") as doc:
                for page in doc:
                    content += page.get_text()
        # Check if file is TXT
        elif filename.endswith('.txt'):
            content = downloaded_file.decode('utf-8')
        else:
            bot.reply_to(message, "❌ I only support PDF or .txt files.")
            return

        if not content.strip():
            bot.reply_to(message, "⚠️ I couldn't find any text in that file.")
            return

        user_id = message.from_user.id

        # 1. Gemini Brain: Generate Questions
        prompt = f"""
        You are a PhD Examiner. Read this thesis chapter and:
        1. Generate 10 difficult defense questions.
        2. Provide a 'Model Answer' for each question.
        3. Explain the academic logic behind each question.
        
        THESIS CONTENT: {content[:15000]} 
        """
        response = model.generate_content(prompt)
        analysis_results = response.text

        # 2. Supabase: Save for learning/history
        data = {
            "user_id": str(user_id),
            "chapter_title": filename,
            "content": content[:5000], # Store preview to stay within DB limits
            "questions": analysis_results
        }
        supabase.table("theses").insert(data).execute()

        # 3. Email the results
        email_sent = send_email(f"Thesis Defense Prep: {filename}", analysis_results)

        # 4. Final Reply
        final_reply = f"**Generated Defense Questions:**\n\n{analysis_results[:1000]}..." 
        if email_sent:
            final_reply += f"\n\n✅ The full report has been sent to {RECEIVER_EMAIL}."
        else:
            final_reply += "\n\n⚠️ Analysis complete but email failed to send."
            
        bot.reply_to(message, final_reply)

    except Exception as e:
        bot.reply_to(message, f"❌ An error occurred: {str(e)}")

# --- 4. START THE BOT ---
if __name__ == "__main__":
    # Start Flask in background
    t1 = Thread(target=run_flask)
    t1.daemon = True
    t1.start()

    # Start self-ping in background
    t2 = Thread(target=self_ping)
    t2.daemon = True
    t2.start()

    print("Bot is starting...")
    try:
        # skip_pending=True prevents 409 Conflict errors
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print(f"Polling Error: {e}")
