import os
import logging
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackContext,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"

# Состояния
WAITING_CAR_SEARCH, WAITING_CAR_CHOICE, WAITING_PHOTO1, WAITING_PHOTO2 = range(4)
user_data_storage = {}

# Главное меню
main_menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        ["🚗 Выбрать авто"],
        ["📸 Отправить фото"]
    ],
    resize_keyboard=True
)

# --- Google Sheets ---
def load_vehicle_data():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    return sheet.worksheet("Vehicles").get_all_records()

def append_inspection(data):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    sheet.worksheet("Inspections").append_row(data)

def append_user_to_vehicles(car_number, user_id, username):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet("Vehicles")
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

# --- Команды ---
async def start_handler(update: Update, context: CallbackContext):
    await update.message.reply_text("👋 Добро пожаловать!\nВыберите действие:", reply_markup=main_menu_keyboard)
    return WAITING_CAR_SEARCH

async def handle_menu_command(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    if text == "🚗 Выбрать авто":
        await update.message.reply_text("Введите 3 цифры из номера автомобиля (например: 333):")
        return WAITING_CAR_SEARCH
    elif text == "📸 Отправить фото":
        await update.message.reply_text("Пожалуйста, отправьте первое фото.")
        return WAITING_PHOTO1
    else:
        await update.message.reply_text("Неизвестная команда. Используйте кнопки меню.")
        return WAITING_CAR_SEARCH

# --- Поиск авто ---
async def search_car_number(update: Update, context: CallbackContext):
    partial_digits = re.sub(r"\D", "", update.message.text.strip())

    if len(partial_digits) != 3:
        await update.message.reply_text("Введите ровно 3 цифры, например: 333")
        return WAITING_CAR_SEARCH

    vehicle_data = load_vehicle_data()
    matches = []
    for v in vehicle_data:
        car_number = v["Номер авто"]
        match_digits = re.findall(r"^[А-ЯA-Z]{1}(\d{3})", car_number)
        if match_digits and match_digits[0] == partial_digits:
            matches.append(v)

    if not matches:
        await update.message.reply_text("🚫 Машины с такими цифрами не найдены.")
        return WAITING_CAR_SEARCH

    keyboard = [
        [InlineKeyboardButton(v["Номер авто"], callback_data=f"choose_{v['Номер авто']}")]
        for v in matches
    ]
    await update.message.reply_text("Выберите ваш автомобиль из списка:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAITING_CAR_CHOICE

async def choose_car_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    car_number = query.data.replace("choose_", "")
    user_id = query.from_user.id
    username = query.from_user.username

    try:
        append_user_to_vehicles(car_number, user_id, username)
        await query.edit_message_text(f"✅ Вы выбрали: {car_number}\nОтправьте первое фото.")
        return WAITING_PHOTO1
    except ValueError as ve:
        await query.edit_message_text(f"🚫 {ve}")
        return WAITING_CAR_SEARCH
    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}")
        await query.edit_message_text("❌ Ошибка при регистрации.")
        return ConversationHandler.END

# --- Фото 1 ---
async def handle_photo1(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return WAITING_PHOTO1
    user_data_storage[chat_id] = {"photo1": update.message.photo[-1].file_id}
    await update.message.reply_text("✅ Фото 1 получено. Теперь отправьте второе.")
    return WAITING_PHOTO2

# --- Фото 2 + сохранение ---
async def handle_photo2(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return WAITING_PHOTO2

    user_data_storage[chat_id]["photo2"] = update.message.photo[-1].file_id

    vehicle_data = load_vehicle_data()
    user_vehicle = None
    for v in vehicle_data:
        if str(v.get("ID (user_id)", "")).strip() == str(user_id):
            user_vehicle = v.get("Номер авто")
            break

    if not user_vehicle:
        await update.message.reply_text("⚠️ Вы ещё не выбрали автомобиль.\nНажмите \"🚗 Выбрать авто\".")
        return WAITING_CAR_SEARCH

    user_data_storage[chat_id]["car_number"] = user_vehicle
    await update.message.reply_text(f"✅ Фото 2 получено. Используем авто: {user_vehicle}\nСохраняем данные…")
    return await save_inspection(update, context)

# --- Сохранение записи ---
async def save_inspection(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_data = user_data_storage.get(chat_id, {})
    car_number = user_data.get("car_number")
    username = update.effective_user.username or ""
    user_id = update.effective_user.id

    now = datetime.now()
    row = [
        now.strftime("%d.%m.%Y"),
        now.strftime("%H:%M"),
        car_number,
        username,
        user_data.get("photo1"),
        user_data.get("photo2"),
        user_id
    ]
    try:
        append_inspection(row)
        await update.message.reply_text("✅ Всё сохранено. Спасибо!")
    except Exception as e:
        logger.error(f"Ошибка записи: {e}")
        await update.message.reply_text("⚠️ Ошибка при сохранении.")
    return ConversationHandler.END

# --- Команды бота ---
async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Начать работу")
    ])

# --- Запуск ---
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_handler)],
        states={
            WAITING_CAR_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_car_number)
            ],
            WAITING_CAR_CHOICE: [
                CallbackQueryHandler(choose_car_button, pattern=r"^choose_")
            ],
            WAITING_PHOTO1: [MessageHandler(filters.PHOTO, handle_photo1)],
            WAITING_PHOTO2: [MessageHandler(filters.PHOTO, handle_photo2)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)

    # Глобальная обработка кнопок
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^(🚗 Выбрать авто|📸 Отправить фото)$"),
        handle_menu_command
    ))

    app.post_init = set_bot_commands

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=os.getenv("WEBHOOK_URL")
    )

if __name__ == "__main__":
    main()
