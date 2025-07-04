import os
import logging
import json
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# Авторизация Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client = gspread.authorize(creds)

sheet = client.open_by_key(SPREADSHEET_ID)
car_sheet = sheet.worksheet("Cars")
inspection_sheet = sheet.worksheet("Inspections")

data = car_sheet.get_all_records()


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот таксопарка.")


# Команда /notify — рассылка
async def notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"{row['Госномер']}", callback_data=json.dumps([row["Госномер"]]))]
        for row in data
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите авто для рассылки:", reply_markup=markup)


# Обработка кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_values = json.loads(query.data)
    selected_rows = [row for row in data if str(row.get("Госномер")) in selected_values]

    success = 0
    failed = 0

    for entry in selected_rows:
        try:
            contact = str(entry["Телефон водителя"]).strip()
            car_number = str(entry["Госномер"]).strip()
            message_text = f"📸 Пожалуйста, отправьте 2 фото автомобиля {car_number} (внутри и снаружи)."

            await context.bot.send_message(chat_id=contact, text=message_text)
            logger.info(f"✅ Сообщение отправлено [{contact}] для машины {car_number}")
            success += 1
        except Exception as e:
            contact_info = str(entry.get("Телефон водителя", "неизвестен"))
            car_number = str(entry.get("Госномер", "неизвестен"))
            logger.error(f"❌ Ошибка отправки [{contact_info}] для машины {car_number}: {e}")
            failed += 1

    await query.edit_message_text(
        text=f"Рассылка завершена.\n✅ Успешно: {success}\n❌ Ошибки: {failed}"
    )


# Получение фото от водителя
user_photos = {}

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    photo_file_id = update.message.photo[-1].file_id

    if user_id not in user_photos:
        user_photos[user_id] = []

    user_photos[user_id].append(photo_file_id)

    if len(user_photos[user_id]) == 1:
        await update.message.reply_text("✅ Фото 1 получено. Теперь отправьте второе фото.")
    elif len(user_photos[user_id]) == 2:
        await update.message.reply_text("✅ Оба фото получены. Теперь введите номер автомобиля (госномер).")


# Получение номера авто после двух фото
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id in user_photos and len(user_photos[user_id]) == 2:
        car_number = update.message.text.strip()
        row = [car_number, user_id, user_photos[user_id][0], user_photos[user_id][1]]
        inspection_sheet.append_row(row)
        await update.message.reply_text("✅ Спасибо! Фото успешно сохранены.")
        user_photos.pop(user_id)
    else:
        await update.message.reply_text("📸 Пожалуйста, сначала отправьте 2 фото автомобиля.")


# Основной запуск
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("notify", notify))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("🤖 Бот запущен.")
    app.run_polling()
