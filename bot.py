
import logging
import os
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackContext,
    CallbackQueryHandler, MessageHandler, filters
)
from google.oauth2.service_account import Credentials
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"

# Чтение таблицы
def load_vehicle_data():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = sheet.worksheet("Vehicles")
    data = worksheet.get_all_records()
    return data

# Хендлер команды /admin
async def admin_handler(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    vehicle_data = load_vehicle_data()

    keyboard = []
    for idx, entry in enumerate(vehicle_data):
        number = entry["Номер авто"]
        keyboard.append([InlineKeyboardButton(f"🚘 {number}", callback_data=f"car_{idx}")])

    keyboard.append([InlineKeyboardButton("📤 Разослать напоминание", callback_data="send_notify")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите автомобили и отправьте напоминание:", reply_markup=reply_markup)

# Обработка кнопок
selected_indices = set()

async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("car_"):
        idx = int(query.data.split("_")[1])
        if idx in selected_indices:
            selected_indices.remove(idx)
        else:
            selected_indices.add(idx)
        await query.edit_message_text("✅ Автомобили выбраны. Нажмите '📤 Разослать напоминание'.")

    elif query.data == "send_notify":
        vehicle_data = load_vehicle_data()
        for idx in selected_indices:
            try:
                entry = vehicle_data[idx]
                phone = entry["Телефон водителя"]
                if phone.startswith("+"):
                    await context.bot.send_message(chat_id=phone, text="📸 Пожалуйста, пришлите 2 фото вашего автомобиля и номер авто.")
            except Exception as e:
                logger.error(f"Ошибка отправки: {e}")
        await query.edit_message_text("✅ Напоминания отправлены.")

def main():
    application = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    application.add_handler(CommandHandler("admin", admin_handler))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()

if __name__ == "__main__":
    main()
