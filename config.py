import os
from dotenv import load_dotenv

load_dotenv('.env')

API_URL = os.getenv('API_URL')
BOT_TOKEN = os.getenv('BOT_TOKEN')