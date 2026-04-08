import os
import telebot
import google.generativeai as genai
from supabase import create_client, Client
from flask import Flask
from threading import Thread

# 1. Setup Configurations
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

# Initialize Clients
bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Flask server for Render/Cron-job pings
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is Running"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# 2. Bot Logic
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Welcome! Please upload your Thesis chapter (as a PDF or text). I will analyze it and generate defense questions.")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # In a real app, use PyMuPDF to extract text from PDF. 
    # For now, we assume it's a text-based document:
    content = downloaded_file.decode('utf-8')
    user_id = message.from_user.id

    bot.reply_to(message, "Processing chapter... please wait.")

    # 3. Gemini Brain: Generate Questions
    prompt = f"""
    You are a PhD Examiner. Read this thesis chapter and generate 5 difficult 
    defense questions that test the validity and methodology. 
    Explain why you are asking each question.
    THESIS CONTENT: {content[:10000]} 
    """
    response = model.generate_content(prompt)
    questions = response.text

    # 4. Supabase: Save to "Learn" and remember
    data = {
        "user_id": str(user_id),
        "chapter_title": message.document.file_name,
        "content": content,
        "questions": questions
    }
    supabase.table("theses").insert(data).execute()

    bot.reply_to(message, f"**Generated Defense Questions:**\n\n{questions}")

# Start the Keep-Alive server
if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.start()
    bot.infinity_polling()
