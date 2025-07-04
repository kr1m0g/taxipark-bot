import logging
import os
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    InputFile
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import gspread
from dotenv import load_dotenv

# Настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 6350035236  # <-- твой Telegram ID
SHEET_NAME = os.getenv("SHEET_NAME")

# Google Sheets
gc = gspread.service_account(filename='credentials.json')
worksheet = gc.open(SHEET_NAME).sheet1

# Состояния
CHOOSING_CAR, CONFIRM_CAR, MAIN_MENU, WAITING_FOR_PHOTO, CHANGING_CAR = range(5)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_available_cars():
    records = worksheet.get_all_records()
    return [r["Номер авто"] for r in records if not r["ID (user_id)"]]

def get_car_by_user(user_id):
    records = worksheet.get_all_records()
    for row in records:
        if str(row["ID (user_id)"]) == str(user_id):
            return row["Номер авто"]
    return None

def assign_car(user_id, username, car_number):
    cell = worksheet.find(car_number)
    if not cell:
        return False
    row = cell.row
    worksheet.update(f'B{row}', str(user_id))
    worksheet.update(f'C{row}', username or "")
    return True

def clear_old_car(user_id):
    records = worksheet.get_all_records()
    for idx, row in enumerate(records, start=2):
        if str(row["ID (user_id)"]) == str(user_id):
            worksheet.update(f'B{idx}', "")
            worksheet.update(f'C{idx}', "")

def build_car_keyboard(car_list):
    return InlineKeyboardMarkup([[InlineKeyboardButton(car, callback_data=car)] for car in car_list])

def get_main_user_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📷 Отправить фото", callback_data="send_photo")],
        [InlineKeyboardButton("🔄 Сменить авто", callback_data="change_car")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    car = get_car_by_user(user_id)
    if car:
        await update.message.reply_text(f"Вы уже зарегистрированы за автомобилем {car}", reply_markup=get_main_user_keyboard())
        return MAIN_MENU
    cars = get_available_cars()
    if not cars:
        await update.message.reply_text("Нет доступных автомобилей.")
        return ConversationHandler.END
    await update.message.reply_text("Выберите доступный автомобиль:", reply_markup=build_car_keyboard(cars))
    return CHOOSING_CAR

async def choose_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["selected_car"] = query.data
    await query.edit_message_text(f"Подтвердите выбор автомобиля: {query.data}", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_car")],
        [InlineKeyboardButton("↩️ Назад", callback_data="back_to_cars")]
    ]))
    return CONFIRM_CAR

async def confirm_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    car = context.user_data.get("selected_car")
    user = update.effective_user

    if car not in get_available_cars():
        await query.edit_message_text("Этот автомобиль уже занят. Попробуйте снова.")
        return await start(update, context)

    assign_car(user.id, user.username, car)
    await query.edit_message_text(f"Вы зарегистрированы за авто: {car}", reply_markup=get_main_user_keyboard())
    return MAIN_MENU

async def back_to_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cars = get_available_cars()
    await update.callback_query.edit_message_text("Выберите автомобиль:", reply_markup=build_car_keyboard(cars))
    return CHOOSING_CAR

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "send_photo":
        await query.edit_message_text("Пожалуйста, отправьте фото автомобиля.")
        return WAITING_FOR_PHOTO
    elif query.data == "change_car":
        cars = get_available_cars()
        await query.edit_message_text("Выберите новый автомобиль:", reply_markup=build_car_keyboard(cars))
        return CHANGING_CAR

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    car = get_car_by_user(user_id)
    if not car:
        await update.message.reply_text("Вы не зарегистрированы.")
        return ConversationHandler.END
    photo_file = await update.message.photo[-1].get_file()
    caption = f"Фото от пользователя ID: {user_id}\nАвто: {car}"
    await photo_file.download_to_drive("last_photo.jpg")
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=InputFile("last_photo.jpg"), caption=caption)
    await update.message.reply_text("Фото отправлено администратору.", reply_markup=get_main_user_keyboard())
    return MAIN_MENU

async def change_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    car = query.data
    user = update.effective_user

    if car not in get_available_cars():
        await query.edit_message_text("Автомобиль уже занят.")
        return CHANGING_CAR

    clear_old_car(user.id)
    assign_car(user.id, user.username, car)
    await query.edit_message_text(f"Вы успешно сменили автомобиль на: {car}", reply_markup=get_main_user_keyboard())
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_CAR: [CallbackQueryHandler(choose_car)],
            CONFIRM_CAR: [
                CallbackQueryHandler(confirm_car, pattern="^confirm_car$"),
                CallbackQueryHandler(back_to_cars, pattern="^back_to_cars$")
            ],
            MAIN_MENU: [CallbackQueryHandler(handle_menu_buttons)],
            WAITING_FOR_PHOTO: [MessageHandler(filters.PHOTO, receive_photo)],
            CHANGING_CAR: [CallbackQueryHandler(change_car)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    main()
