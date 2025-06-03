import os
import logging
import sqlite3
import json
from datetime import datetime, date
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Конфигурация ---
TOKEN = os.getenv('TELEGRAM_TOKEN', '7806769211:AAFWCXODWkKGeB1ccFhBf9H4gDNgo43df6E')  # Токен бота
DB_PATH = 'fitobob.db'

# Суточные цели по умолчанию (можно менять командой /targets)
DEFAULT_TARGETS = {
    'calories': 1800,
    'protein': 120,
    'fat': 50,
    'carbs': 100
}

# База продуктов с указанием БЖУ и калорий на 100г (русские названия)
NUTRITION_DB = {
    'яйцо':     {'calories': 155, 'protein': 13, 'fat': 11, 'carbs': 1.1},  # 100 г варёных яиц
    'рис':      {'calories': 130, 'protein': 2.7, 'fat': 0.3, 'carbs': 28},
    'курица':   {'calories': 165, 'protein': 31, 'fat': 3.6, 'carbs': 0},
    'говядина': {'calories': 250, 'protein': 26, 'fat': 17, 'carbs': 0},
    'яблоко':   {'calories': 52, 'protein': 0.3, 'fat': 0.2, 'carbs': 14},
    'банан':    {'calories': 89, 'protein': 1.1, 'fat': 0.3, 'carbs': 23},
    'брокколи': {'calories': 55, 'protein': 3.7, 'fat': 0.6, 'carbs': 11},
    'лосось':   {'calories': 208, 'protein': 20, 'fat': 13, 'carbs': 0},
    'миндаль':  {'calories': 579, 'protein': 21, 'fat': 50, 'carbs': 22},
    'протеин':  {'calories': 110, 'protein': 20, 'fat': 1, 'carbs': 3},
    'панель':   {'calories': 350, 'protein': 5, 'fat': 15, 'carbs': 50},  # пример торта
    'арбуз':    {'calories': 30, 'protein': 0.6, 'fat': 0.2, 'carbs': 8},
    'свинина':  {'calories': 300, 'protein': 25, 'fat': 20, 'carbs': 0},
    'суп':      {'calories': 30, 'protein': 2, 'fat': 1, 'carbs': 3},
}

# --- Работа с базой данных ---

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Таблица пользователей
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            targets TEXT
        )
    ''')
    # Таблица логов еды
    c.execute('''
        CREATE TABLE IF NOT EXISTS food_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            food TEXT,
            qty REAL,
            unit TEXT,
            calories REAL,
            protein REAL,
            fat REAL,
            carbs REAL,
            date TEXT
        )
    ''')
    conn.commit()
    conn.close()


def get_user_targets(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT targets FROM users WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    else:
        return DEFAULT_TARGETS.copy()


def set_user_targets(user_id, targets_dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    targets_json = json.dumps(targets_dict)
    c.execute('REPLACE INTO users (user_id, targets) VALUES (?, ?)', (user_id, targets_json))
    conn.commit()
    conn.close()


def log_food(user_id, food, qty, diet_unit):
    # Получаем данные из базы
    nutrition = NUTRITION_DB.get(food)
    if not nutrition:
        return None
    multiplier = qty / 100 if diet_unit == 'g' else qty * 50 / 100  # 1 шт = 50 г
    calories = nutrition['calories'] * multiplier
    protein = nutrition['protein'] * multiplier
    fat = nutrition['fat'] * multiplier
    carbs = nutrition['carbs'] * multiplier
    date_str = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO food_log (user_id, food, qty, unit, calories, protein, fat, carbs, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, food, qty, diet_unit, calories, protein, fat, carbs, date_str))
    conn.commit()
    conn.close()
    return calories, protein, fat, carbs


def get_daily_summary(user_id, date_str=None):
    if not date_str:
        date_str = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT SUM(calories), SUM(protein), SUM(fat), SUM(carbs)
        FROM food_log
        WHERE user_id=? AND date=?
    ''', (user_id, date_str))
    row = c.fetchone()
    conn.close()
    if row and row[0] is not None:
        return {
            'calories': row[0],
            'protein': row[1],
            'fat': row[2],
            'carbs': row[3]
        }
    else:
        return {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0}

# --- Обработчики команд бота ---

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    init_db()
    # Инициализируем пользователя в БД
    get_user_targets(user.id)
    update.message.reply_text(
        f"Привет, {user.first_name}! Я FitoBob, твой фитнес-бот.\n" +
        "Я помогу считать калории и макронутриенты.\n" +
        "Используй /help для списка команд."
    )


def help_command(update: Update, context: CallbackContext):
    help_text = (
        "Список команд FitoBob:\n"
        "/log <еда> <количество> <g|шт> - добавить еду. Пример: /log яйцо 2 шт, /log рис 150 g\n"
        "/summary - показать, сколько ты сегодня съел и сколько осталось до цели\n"
        "/targets <калории> <белок> <жиры> <угли> - установить свои цели\n"
        "/reset - очистить дневной лог (только сегодня)\n"
        "/help - показать это сообщение"
    )
    update.message.reply_text(help_text)


def set_targets(update: Update, context: CallbackContext):
    user = update.effective_user
    try:
        args = context.args
        if len(args) != 4:
            raise ValueError
        cal, prot, fat, carbs = map(int, args)
        new_targets = {
            'calories': cal,
            'protein': prot,
            'fat': fat,
            'carbs': carbs
        }
        set_user_targets(user.id, new_targets)
        update.message.reply_text(f"Цели обновлены: {cal} ккал, {prot} г белка, {fat} г жира, {carbs} г углеводов.")
    except:
        update.message.reply_text("Использование: /targets <калории> <белок> <жиры> <угли>")


def log_food_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if len(context.args) < 3:
        update.message.reply_text("Использование: /log <еда> <количество> <g|шт>. Пример: /log яйцо 2 шт")
        return
    food = context.args[0].lower()
    try:
        qty = float(context.args[1])
    except:
        update.message.reply_text("Количество должно быть числом. Пример: /log рис 150 g")
        return
    unit = context.args[2].lower()
    if food not in NUTRITION_DB:
        update.message.reply_text(f"Не знаю продукт '{food}'. Доступные продукты: {', '.join(NUTRITION_DB.keys())}")
        return
    if unit not in ['g', 'шт']:
        update.message.reply_text("Единица должна быть 'g' или 'шт'. Пример: /log яйцо 2 шт, /log рис 150 g")
        return
    result = log_food(user.id, food, qty, unit)
    if not result:
        update.message.reply_text("Не удалось добавить продукт. Проверь название и единицу.")
        return
    cals, prot, fat, carbs = result
    summary = get_daily_summary(user.id)
    targets = get_user_targets(user.id)
    reply = (
        f"Добавлено: {food} {int(qty)}{unit}\n"
        f"⇨ {int(cals)} ккал, {int(prot)} г белка, {int(fat)} г жира, {int(carbs)} г углеводов.\n"
        f"Сегодня: {int(summary['calories'])}/{targets['calories']} ккал, "
        f"{int(summary['protein'])}/{targets['protein']} г белка"
    )
    update.message.reply_text(reply)


def summary_command(update: Update, context: CallbackContext):
    user = update.effective_user
    summary = get_daily_summary(user.id)
    targets = get_user_targets(user.id)
    reply = (
        f"📋 Ежедневный отчёт ({date.today().isoformat()}):\n"
        f"Калории: {int(summary['calories'])}/{targets['calories']}\n"
        f"Белок: {int(summary['protein'])}/{targets['protein']} г\n"
        f"Жир: {int(summary['fat'])}/{targets['fat']} г\n"
        f"Углеводы: {int(summary['carbs'])}/{targets['carbs']} г\n"
    )
    update.message.reply_text(reply)


def reset_command(update: Update, context: CallbackContext):
    user = update.effective_user
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = date.today().isoformat()
    c.execute('DELETE FROM food_log WHERE user_id=? AND date=?', (user.id, today))
    conn.commit()
    conn.close()
    update.message.reply_text("Лог за сегодня очищен.")


def unknown(update: Update, context: CallbackContext):
    update.message.reply_text("Не понимаю команду. Используй /help.")

# --- Основной запуск бота ---

def main():
    init_db()
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("targets", set_targets))
    dp.add_handler(CommandHandler("log", log_food_command))
    dp.add_handler(CommandHandler("summary", summary_command))
    dp.add_handler(CommandHandler("reset", reset_command))
    dp.add_handler(MessageHandler(Filters.command, unknown))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
