import logging
import os
import re
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackContext,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from google.oauth2.service_account import Credentials
from datetime import datetime

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"

def load_vehicle_data():
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID)
        return sheet.worksheet("Vehicles").get_all_records()
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных: {e}")
        return []

def append_inspection(data):
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID)
        sheet.worksheet("Inspections").append_row(data)
    except Exception as e:
        logger.error(f"Ошибка при записи осмотра: {e}")

def append_user_to_vehicles(car_number, user_id, username):
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID)
        worksheet = sheet.worksheet("Vehicles")
        all_values = worksheet.get_all_values()

        for i, row in enumerate(all_values[1:], start=2):
            existing_car = row[0].strip().upper() if len(row) > 0 else ""
            existing_id = row[1].strip() if len(row) > 1 else ""

            if existing_car == car_number:
                if existing_id:
                    raise ValueError("Этот автомобиль уже зарегистрирован другим водителем.")
                else:
                    worksheet.update_cell(i, 2, str(user_id))
                    worksheet.update_cell(i, 3, username or "")
                    return

        worksheet.append_row([car_number, str(user_id), username or ""])
    except Exception as e:
        logger.error(f"Ошибка при добавлении пользователя: {e}")
