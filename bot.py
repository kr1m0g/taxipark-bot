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

# Логи
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"

# Состояния
WAITING_PHOTO1, WAITING_PHOTO2, WAITING_CAR_NUMBER, WAITING_REG_CAR = range(4)
user_data_storage = {}

# Загрузка данных авто
def load_vehicle_data():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = sheet.worksheet("Vehicles")
    return worksheet.get_all_records()

# Запись осмотра
def append_inspection(data):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = sheet.worksheet("Inspections")
    worksheet.append_row(data)

# Сохранить водителя
def save_vehicle_record(car_number, telegram_id, username):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = sheet.worksheet("Vehicles")

    existing = worksheet.get_all_records()
    for row in existing:
        if str(row.get("Telegram ID", "")).strip() == str(telegram_id):
            return  # Уже есть

    contact = f"@{username}" if username else str(telegram_id)
    worksheet.append_row([car_number, contact, telegram_id])

# Старт: регистрация
async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_data_storage[chat_id] = {}
    await update.message.reply_text("👋 Добро пожаловать! Введите номер вашего автомобиля:")
    return WAITING_REG_CAR

# Обработка регистрации
async def handle_registration_car(update: Update, context: CallbackContext):
    car_number = update.message.text.strip().upper()
    telegram_id = update.effective_user.id
    username = update.effective_user.username

    try:
        save_vehicle_record(car_number, telegram_id, username)
        await update.message.reply_text(f"✅ Вы зарегистрированы с авто {car_number}. Ожидайте напоминание для осмотра.")
    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}")
        await update.message.reply_text("⚠️ Не удалось зарегистрировать. Попробуйте позже.")
    return ConversationHandler.END

# Получение фото 1
async def handle_photo1(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте первую фотографию.")
        return WAITING_PHOTO1

    file_id = update.message.photo[-1].file_id
    user_data_storage[chat_id] = {"photo1": file_id}
    await update.message.reply_text("✅ Фото 1 получено. Теперь отправьте второе фото.")
    return WAITING_PHOTO2

# Получение фото 2
async def handle_photo2(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте вторую фотографию.")
        return WAITING_PHOTO2

    file_id = update.message.photo[-1].file_id
    user_data_storage[chat_id]["photo2"] = file_id
    await update.message.reply_text("✅ Фото 2 получено. Теперь отправьте номер автомобиля (например: А123АА).")
    return WAITING_CAR_NUMBER

# Обработка номера автомобиля
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
        str(phone),
        photo1,
        photo2,
        update.effective_user.id
    ]
    try:
        append_inspection(row)
        await update.message.reply_text("✅ Осмотр сохранён. Спасибо!")
    except Exception as e:
        logger.error(f"Ошибка при записи в таблицу: {e}")
        await update.message.reply_text("⚠️ Ошибка при сохранении.")
    return ConversationHandler.END

# Команда /admin
async def admin_handler(update: Update, context: CallbackContext):
    vehicle_data = load_vehicle_data()
    keyboard = []
    for idx, entry in enumerate(vehicle_data):
        number = entry["Номер авто"]
        keyboard.append([InlineKeyboardButton(f"🚘 {number}", callback_data=f"car_{idx}")])
    keyboard.append([InlineKeyboardButton("📤 Разослать напоминание", callback_data="send_notify")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите авто для рассылки:", reply_markup=reply_markup)

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

        selected = ", ".join(str(i + 1) for i in selected_indices)
        await query.edit_message_text(
            f"✅ Выбраны авто: {selected}\nНажмите 📤 для рассылки.",
            reply_markup=query.message.reply_markup
        )

    elif query.data == "send_notify":
        vehicle_data = load_vehicle_data()
        sent = 0
        for idx in selected_indices:
            try:
                entry = vehicle_data[idx]
                contact = entry["Телефон водителя"].strip()
                message_text = "📸 Пожалуйста, пришлите 2 фото автомобиля и номер авто."

                if contact.startswith("@"):
                    await context.bot.send_message(chat_id=contact, text=message_text)
                    sent += 1
                else:
                    await context.bot.send_message(chat_id=int(contact), text=message_text)
                    sent += 1

            except Exception as e:
                logger.error(f"❌ Ошибка отправки [{contact}]: {e}")

        await query.edit_message_text(f"✅ Напоминания отправлены: {sent} водителям.")
        selected_indices.clear()

# Запуск
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.PHOTO, handle_photo1),
        ],
        states={
            WAITING_REG_CAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration_car)],
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
