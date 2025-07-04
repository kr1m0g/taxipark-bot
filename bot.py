import logging
import os
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackContext,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
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

def append_inspection(data):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = sheet.worksheet("Inspections")
    worksheet.append_row(data)

# Переменные состояний
WAITING_PHOTO1, WAITING_PHOTO2, WAITING_CAR_NUMBER = range(3)

user_data_storage = {}

# Старт: приём фото
async def handle_photo1(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return WAITING_PHOTO1

    file_id = update.message.photo[-1].file_id
    user_data_storage[chat_id] = {"photo1": file_id}
    await update.message.reply_text("✅ Фото 1 получено. Теперь отправьте второе фото.")
    return WAITING_PHOTO2

async def handle_photo2(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return WAITING_PHOTO2

    file_id = update.message.photo[-1].file_id
    user_data_storage[chat_id]["photo2"] = file_id
    await update.message.reply_text("✅ Фото 2 получено. Теперь отправьте номер автомобиля (например: А123АА).")
    return WAITING_CAR_NUMBER

async def handle_car_number(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    car_number = update.message.text.strip().upper()

    user_data = user_data_storage.get(chat_id, {})
    photo1 = user_data.get("photo1")
    photo2 = user_data.get("photo2")
    phone = update.effective_user.username or update.effective_user.id

    now = datetime.now()
    row = [
        now.strftime("%d.%m.%Y"),
        now.strftime("%H:%M"),
        car_number,
        phone,
        photo1,
        photo2,
        update.effective_user.id
    ]
    try:
        append_inspection(row)
        await update.message.reply_text("✅ Данные успешно сохранены. Спасибо!")
    except Exception as e:
        logger.error(f"Ошибка записи в таблицу: {e}")
        await update.message.reply_text("⚠️ Ошибка при сохранении данных.")
    return ConversationHandler.END

# Админ-панель
async def admin_handler(update: Update, context: CallbackContext):
    vehicle_data = load_vehicle_data()
    keyboard = []
    for idx, entry in enumerate(vehicle_data):
        number = entry["Номер авто"]
        keyboard.append([InlineKeyboardButton(f"🚘 {number}", callback_data=f"car_{idx}")])
    keyboard.append([InlineKeyboardButton("📤 Разослать напоминание", callback_data="send_notify")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите автомобили и отправьте напоминание:", reply_markup=reply_markup)

# Выбор и рассылка
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
                phone_str = str(phone)
                if phone_str.startswith("+"):
                    await context.bot.send_message(chat_id=phone_str, text="📸 Пожалуйста, пришлите 2 фото автомобиля и номер авто.")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления: {e}")
        await query.edit_message_text("✅ Напоминания отправлены.")

def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, handle_photo1)],
        states={
            WAITING_PHOTO2: [MessageHandler(filters.PHOTO, handle_photo2)],
            WAITING_CAR_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_car_number)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("admin", admin_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()

if __name__ == "__main__":
    main()