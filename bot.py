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

def append_user_to_vehicles(car_number, user_id, username):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = sheet.worksheet("Vehicles")
    existing_records = worksheet.get_all_records()
    for record in existing_records:
        if str(record.get("ID", "")) == str(user_id):
            return
    worksheet.append_row([car_number, str(user_id), username or ""])

# Состояния
WAITING_CAR_SEARCH, WAITING_CAR_CHOICE, WAITING_PHOTO1, WAITING_PHOTO2, WAITING_CAR_NUMBER = range(5)

user_data_storage = {}
selected_indices = set()

# /start
async def start_handler(update: Update, context: CallbackContext):
    await update.message.reply_text("👋 Добро пожаловать!\nВведите первые 3 символа номера автомобиля:")
    return WAITING_CAR_SEARCH

# Поиск по 3 символам
async def search_car_number(update: Update, context: CallbackContext):
    partial = update.message.text.strip().upper()
    if len(partial) < 3:
        await update.message.reply_text("Введите минимум 3 символа номера авто.")
        return WAITING_CAR_SEARCH

    vehicle_data = load_vehicle_data()
    matches = [v for v in vehicle_data if v["Номер авто"].startswith(partial)]

    if not matches:
        await update.message.reply_text("🚫 Ничего не найдено. Попробуйте ещё.")
        return WAITING_CAR_SEARCH

    keyboard = [
        [InlineKeyboardButton(v["Номер авто"], callback_data=f"choose_{v['Номер авто']}")]
        for v in matches
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите ваш автомобиль:", reply_markup=reply_markup)
    return WAITING_CAR_CHOICE

# Выбор авто из списка
async def choose_car_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    car_number = query.data.replace("choose_", "")
    user_id = query.from_user.id
    username = query.from_user.username

    try:
        append_user_to_vehicles(car_number, user_id, username)
        await query.edit_message_text(f"✅ Вы выбрали автомобиль: {car_number}\nТеперь отправьте первое фото.")
        return WAITING_PHOTO1
    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}")
        await query.edit_message_text("Ошибка при регистрации. Попробуйте позже.")
        return ConversationHandler.END

# Фото 1
async def handle_photo1(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return WAITING_PHOTO1
    file_id = update.message.photo[-1].file_id
    user_data_storage[chat_id] = {"photo1": file_id}
    await update.message.reply_text("✅ Фото 1 получено. Теперь отправьте второе фото.")
    return WAITING_PHOTO2

# Фото 2
async def handle_photo2(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return WAITING_PHOTO2
    file_id = update.message.photo[-1].file_id
    user_data_storage[chat_id]["photo2"] = file_id
    await update.message.reply_text("✅ Фото 2 получено. Теперь отправьте номер автомобиля (например: А123АА).")
    return WAITING_CAR_NUMBER

# Завершение — сохранить в Inspections
async def handle_car_number(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    car_number = update.message.text.strip().upper()
    user_data = user_data_storage.get(chat_id, {})
    photo1 = user_data.get("photo1")
    photo2 = user_data.get("photo2")
    now = datetime.now()
    row = [
        now.strftime("%d.%m.%Y"),
        now.strftime("%H:%M"),
        car_number,
        update.effective_user.username or "",
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

# /admin — панель выбора авто
async def admin_handler(update: Update, context: CallbackContext):
    vehicle_data = load_vehicle_data()
    keyboard = []
    for idx, entry in enumerate(vehicle_data):
        number = entry["Номер авто"]
        keyboard.append([InlineKeyboardButton(f"🚘 {number}", callback_data=f"car_{idx}")])
    keyboard.append([InlineKeyboardButton("📤 Разослать напоминание", callback_data="send_notify")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите автомобили и отправьте напоминание:", reply_markup=reply_markup)

# Обработка кнопок админа
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
                user_id = entry.get("ID")
                if user_id:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text="📸 Пожалуйста, пришлите 2 фото автомобиля и номер авто."
                    )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления: {e}")
        await query.edit_message_text("✅ Напоминания отправлены.")

# Webhook-запуск
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    # Conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_handler)],
        states={
            WAITING_CAR_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_car_number)],
            WAITING_CAR_CHOICE: [CallbackQueryHandler(choose_car_button, pattern=r"^choose_")],
            WAITING_PHOTO1: [MessageHandler(filters.PHOTO, handle_photo1)],
            WAITING_PHOTO2: [MessageHandler(filters.PHOTO, handle_photo2)],
            WAITING_CAR_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_car_number)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("admin", admin_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Webhook-запуск
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=os.getenv("WEBHOOK_URL")
    )

if __name__ == "__main__":
    main()
