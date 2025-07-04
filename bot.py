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

# Тестовое подключение к таблице
try:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    logger.info("✅ Таблица найдена: %s", sheet.title)
except Exception as e:
    logger.error("❌ Ошибка доступа к таблице: %s", e)

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
            worksheet.update_cell(i, 2, str(user_id))
            worksheet.update_cell(i, 3, username or "")
            return
    worksheet.append_row([car_number, str(user_id), username or ""])

# Числовые константы состояний
WAITING_CAR_SEARCH, WAITING_CAR_CHOICE, WAITING_PHOTO1, WAITING_PHOTO2, WAITING_CAR_NUMBER = range(5)

user_data_storage = {}
selected_indices = set()

# ID админа
ADMIN_ID = 6350035236

# Команда /start
async def start_handler(update: Update, context: CallbackContext):
    await update.message.reply_text("👋 Привет! Введите минимум 2 цифры из номера вашего авто:")
    return WAITING_CAR_SEARCH

# Поиск авто по цифрам
async def search_car_number(update: Update, context: CallbackContext):
    partial = re.sub(r"\D", "", update.message.text.strip())
    if len(partial) < 2:
        await update.message.reply_text("Введите хотя бы 2 цифры.")
        return WAITING_CAR_SEARCH
    matches = [v for v in load_vehicle_data()
               if partial in re.sub(r"\D", "", v["Номер авто"])]
    if not matches:
        await update.message.reply_text("🚫 Не найдено.")
        return WAITING_CAR_SEARCH
    keyboard = [[InlineKeyboardButton(v["Номер авто"], callback_data=f"choose_{v['Номер авто']}")]
                for v in matches]
    await update.message.reply_text("Выберите авто:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAITING_CAR_CHOICE

# Пользователь выбирает авто
async def choose_car_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    car = query.data.replace("choose_", "")
    try:
        append_user_to_vehicles(car, query.from_user.id, query.from_user.username)
        await query.edit_message_text(f"✅ Вы выбрали: {car}. Отправьте первую фотку.")
        return WAITING_PHOTO1
    except ValueError as ve:
        await query.edit_message_text(f"🚫 {ve}")
        return ConversationHandler.END
    except Exception as e:
        logger.error("Ошибка регистрации: %s", e)
        await query.edit_message_text("❌ Ошибка регистрации.")
        return ConversationHandler.END

# Фото1
async def handle_photo1(update: Update, context: CallbackContext):
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, фото.")
        return WAITING_PHOTO1
    user_data_storage[update.effective_chat.id] = {"photo1": update.message.photo[-1].file_id}
    await update.message.reply_text("✅ Фото 1 — отлично! Теперь пришлите фото 2.")
    return WAITING_PHOTO2

# Фото2
async def handle_photo2(update: Update, context: CallbackContext):
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, фото.")
        return WAITING_PHOTO2
    chat = update.effective_chat.id
    user_data_storage[chat]["photo2"] = update.message.photo[-1].file_id
    await update.message.reply_text("✅ Фото 2 — отлично! Теперь отправьте номер авто снова.")
    return WAITING_CAR_NUMBER

# Завершение регистрации
async def handle_car_number(update: Update, context: CallbackContext):
    chat = update.effective_chat.id
    data = user_data_storage.get(chat, {})
    row = [
        datetime.now().strftime("%d.%m.%Y"),
        datetime.now().strftime("%H:%M"),
        update.message.text.strip().upper(),
        update.effective_user.username or "",
        data.get("photo1"),
        data.get("photo2"),
        update.effective_user.id
    ]
    try:
        append_inspection(row)
        await update.message.reply_text("✅ Всё сохранено. Спасибо!")
    except Exception as e:
        logger.error("Ошибка записи:", e)
        await update.message.reply_text("⚠️ Ошибка при сохранении.")
    return ConversationHandler.END

# Команда /admin
async def admin_handler(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return  # не админ — не реагируем
    selected_indices.clear()
    await send_admin_keyboard(update.message, context)

# Построение кнопок для админа
async def send_admin_keyboard(message_or_query, context: CallbackContext):
    data = load_vehicle_data()
    keyboard = [[InlineKeyboardButton( ("✅" if i in selected_indices else "◻️") + " " + v["Номер авто"],
                                      callback_data=f"car_{i}")]
                for i, v in enumerate(data)]
    if selected_indices:
        keyboard.append([InlineKeyboardButton("📤 Разослать напоминание", callback_data="send_notify")])
    markup = InlineKeyboardMarkup(keyboard)
    if hasattr(message_or_query, "reply_text"):
        await message_or_query.reply_text("Выберите машины:", reply_markup=markup)
    else:
        await message_or_query.edit_message_text("Выберите машины:", reply_markup=markup)

# Обработка admin-кнопок
async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    data = load_vehicle_data()
    if query.data.startswith("car_"):
        idx = int(query.data.split("_")[1])
        if idx in selected_indices:
            selected_indices.remove(idx)
        else:
            selected_indices.add(idx)
        await send_admin_keyboard(query, context)
    elif query.data == "send_notify":
        for idx in selected_indices:
            entry = data[idx]
            uid = entry.get("ID (user_id)")
            if uid:
                try:
                    await context.bot.send_message(chat_id=int(uid),
                                                   text=f"📸 Админ просит: отправьте 2 фото и номер авто ({entry['Номер авто']}).")
                except Exception as e:
                    logger.error("Ошибка отправки %s → %s: %s", entry['Номер авто'], uid, e)
        selected_indices.clear()
        await query.edit_message_text("✅ Напоминания отправлены.")

def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_handler)],
        states={
            WAITING_CAR_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_car_number)],
            WAITING_CAR_CHOICE: [CallbackQueryHandler(choose_car_button, pattern="^choose_")],
            WAITING_PHOTO1: [MessageHandler(filters.PHOTO, handle_photo1)],
            WAITING_PHOTO2: [MessageHandler(filters.PHOTO, handle_photo2)],
            WAITING_CAR_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_car_number)],
        },
        fallbacks=[]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("admin", admin_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_webhook(listen="0.0.0.0", port=int(os.getenv("PORT", 8443)), webhook_url=os.getenv("WEBHOOK_URL"))

if __name__ == "__main__":
    main()
