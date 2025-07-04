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

def remove_user_from_vehicles(user_id):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    worksheet = client.open_by_key(SPREADSHEET_ID).worksheet("Vehicles")
    all_values = worksheet.get_all_values()

    for i, row in enumerate(all_values[1:], start=2):
        if len(row) >= 2 and row[1] == str(user_id):
            worksheet.update_cell(i, 2, "")
            worksheet.update_cell(i, 3, "")
            break

# Состояния
WAITING_CAR_SEARCH, WAITING_CAR_CHOICE, WAITING_PHOTO1, WAITING_PHOTO2, WAITING_CAR_NUMBER = range(5)
user_data_storage = {}
selected_indices = set()

# /start
async def start_handler(update: Update, context: CallbackContext):
    await update.message.reply_text("👋 Добро пожаловать!\nВведите любые цифры из номера автомобиля (например: 333):")
    return WAITING_CAR_SEARCH

# Поиск авто по цифрам
async def search_car_number(update: Update, context: CallbackContext):
    partial_digits = re.sub(r"\D", "", update.message.text.strip())
    if len(partial_digits) < 2:
        await update.message.reply_text("Введите хотя бы 2 цифры.")
        return WAITING_CAR_SEARCH

    vehicle_data = load_vehicle_data()
    matches = []
    for v in vehicle_data:
        car_number = v["Номер авто"]
        digits_only = re.sub(r"\D", "", car_number)
        if partial_digits in digits_only:
            matches.append(v)

    if not matches:
        await update.message.reply_text("🚫 Машины не найдены.")
        return WAITING_CAR_SEARCH

    keyboard = [
        [InlineKeyboardButton(v["Номер авто"], callback_data=f"choose_{v['Номер авто']}")]
        for v in matches
    ]
    await update.message.reply_text("Выберите ваш автомобиль:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAITING_CAR_CHOICE

# Выбор машины
async def choose_car_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    car_number = query.data.replace("choose_", "")
    user_id = query.from_user.id
    username = query.from_user.username

    try:
        append_user_to_vehicles(car_number, user_id, username)
        await query.edit_message_text(
            f"✅ Вы выбрали: {car_number}\nОтправьте первое фото.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Сменить авто", callback_data="change_car")]
            ])
        )
        return WAITING_PHOTO1
    except ValueError as ve:
        await query.edit_message_text(f"🚫 {ve}")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}")
        await query.edit_message_text("❌ Ошибка при регистрации.")
        return ConversationHandler.END

# Обработка смены автомобиля
async def change_car_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    try:
        remove_user_from_vehicles(user_id)
        await query.edit_message_text("🔄 Давайте выберем другой автомобиль.\nВведите цифры из номера:")
        return WAITING_CAR_SEARCH
    except Exception as e:
        logger.error(f"Ошибка при смене авто: {e}")
        await query.edit_message_text("❌ Не удалось сменить автомобиль.")
        return ConversationHandler.END

# Фото 1
async def handle_photo1(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return WAITING_PHOTO1
    user_data_storage[chat_id] = {"photo1": update.message.photo[-1].file_id}
    await update.message.reply_text("✅ Фото 1 получено. Теперь отправьте второе.")
    return WAITING_PHOTO2

# Фото 2
async def handle_photo2(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте фотографию.")
        return WAITING_PHOTO2
    user_data_storage[chat_id]["photo2"] = update.message.photo[-1].file_id
    await update.message.reply_text("✅ Фото 2 получено. Теперь отправьте номер авто (например: А333АН797).")
    return WAITING_CAR_NUMBER

# Завершаем регистрацию
async def handle_car_number(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    car_number = update.message.text.strip().upper()
    user_data = user_data_storage.get(chat_id, {})
    now = datetime.now()
    row = [
        now.strftime("%d.%m.%Y"),
        now.strftime("%H:%M"),
        car_number,
        update.effective_user.username or "",
        user_data.get("photo1"),
        user_data.get("photo2"),
        update.effective_user.id
    ]
    try:
        append_inspection(row)
        await update.message.reply_text("✅ Всё сохранено. Спасибо!")
    except Exception as e:
        logger.error(f"Ошибка записи: {e}")
        await update.message.reply_text("⚠️ Ошибка при сохранении.")
    return ConversationHandler.END

# /admin
async def admin_handler(update: Update, context: CallbackContext):
    selected_indices.clear()
    await send_admin_keyboard(update.message, context)

# Клавиатура админа
async def send_admin_keyboard(message_or_query, context: CallbackContext):
    vehicle_data = load_vehicle_data()
    keyboard = []
    for idx, entry in enumerate(vehicle_data):
        number = entry["Номер авто"]
        selected = "✅" if idx in selected_indices else "◻️"
        keyboard.append([InlineKeyboardButton(f"{selected} {number}", callback_data=f"car_{idx}")])
    if selected_indices:
        keyboard.append([InlineKeyboardButton("📤 Разослать напоминание", callback_data="send_notify")])
    markup = InlineKeyboardMarkup(keyboard)

    if hasattr(message_or_query, "reply_text"):
        await message_or_query.reply_text("Выберите автомобили:", reply_markup=markup)
    else:
        await message_or_query.edit_message_text("Выберите автомобили:", reply_markup=markup)

# Обработка кнопок админа
async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    vehicle_data = load_vehicle_data()

    if query.data.startswith("car_"):
        idx = int(query.data.split("_")[1])
        if idx in selected_indices:
            selected_indices.remove(idx)
        else:
            selected_indices.add(idx)
        await send_admin_keyboard(query, context)

    elif query.data == "send_notify":
        for idx in selected_indices:
            entry = vehicle_data[idx]
            user_id = entry.get("ID (user_id)")
            if user_id:
                try:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text="📸 Пожалуйста, пришлите 2 фото автомобиля и номер авто."
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки {entry['Номер авто']} → {user_id}: {e}")
            else:
                logger.warning(f"🚫 Нет ID у {entry['Номер авто']} — пропущено.")
        selected_indices.clear()
        await query.edit_message_text("✅ Напоминания отправлены.")

# Запуск
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_handler)],
        states={
            WAITING_CAR_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_car_number)],
            WAITING_CAR_CHOICE: [
                CallbackQueryHandler(choose_car_button, pattern=r"^choose_"),
                CallbackQueryHandler(change_car_button, pattern=r"^change_car$")
            ],
            WAITING_PHOTO1: [MessageHandler(filters.PHOTO, handle_photo1)],
            WAITING_PHOTO2: [MessageHandler(filters.PHOTO, handle_photo2)],
            WAITING_CAR_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_car_number)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("admin", admin_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=os.getenv("WEBHOOK_URL")
    )

if __name__ == "__main__":
    main()
