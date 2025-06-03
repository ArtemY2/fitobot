import os
import logging
import sqlite3
import json
from datetime import date

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    logger.error("Переменная окружения TELEGRAM_TOKEN не задана!")
    raise RuntimeError("Не удалось получить TELEGRAM_TOKEN из окружения.")

DB_PATH = 'fitobob.db'

# Суточные цели по умолчанию
DEFAULT_TARGETS = {
    'calories': 1800,
    'protein': 120,
    'fat': 50,
    'carbs': 100
}

# База продуктов (БЖУ и калории на 100 г)
NUTRITION_DB = {
    'яйцо':     {'calories': 155, 'protein': 13,  'fat': 11,  'carbs': 1.1},
    'рис':      {'calories': 130, 'protein': 2.7, 'fat': 0.3, 'carbs': 28},
    'курица':   {'calories': 165, 'protein': 31,  'fat': 3.6, 'carbs': 0},
    'говядина': {'calories': 250, 'protein': 26,  'fat': 17,  'carbs': 0},
    'яблоко':   {'calories': 52,  'protein': 0.3, 'fat': 0.2, 'carbs': 14},
    'банан':    {'calories': 89,  'protein': 1.1, 'fat': 0.3, 'carbs': 23},
    'брокколи': {'calories': 55,  'protein': 3.7, 'fat': 0.6, 'carbs': 11},
    'лосось':   {'calories': 208, 'protein': 20,  'fat': 13,  'carbs': 0},
    'миндаль':  {'calories': 579, 'protein': 21,  'fat': 50,  'carbs': 22},
    'протеин':  {'calories': 110, 'protein': 20,  'fat': 1,   'carbs': 3},
    'панель':   {'calories': 350, 'protein': 5,   'fat': 15,  'carbs': 50},
    'арбуз':    {'calories': 30,  'protein': 0.6, 'fat': 0.2, 'carbs': 8},
    'свинина':  {'calories': 300, 'protein': 25,  'fat': 20,  'carbs': 0},
    'суп':      {'calories': 30,  'protein': 2,   'fat': 1,   'carbs': 3},
}


# ------------------------------
#  Функции работы с БД (SQLite)
# ------------------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Таблица пользователей (ид клиента → JSON целей)
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


def get_user_targets(user_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT targets FROM users WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    else:
        return DEFAULT_TARGETS.copy()


def set_user_targets(user_id: int, targets_dict: dict) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    targets_json = json.dumps(targets_dict, ensure_ascii=False)
    c.execute(
        'REPLACE INTO users (user_id, targets) VALUES (?, ?)',
        (user_id, targets_json)
    )
    conn.commit()
    conn.close()


def log_food_to_db(user_id: int, food: str, qty: float, diet_unit: str):
    nutrition = NUTRITION_DB.get(food)
    if not nutrition:
        return None

    # Если единица «g» → берем qty грамм, если «шт» → считаем, что 1 шт = 50 г
    multiplier = (qty / 100) if (diet_unit == 'g') else (qty * 50 / 100)
    calories = nutrition['calories'] * multiplier
    protein  = nutrition['protein']  * multiplier
    fat      = nutrition['fat']      * multiplier
    carbs    = nutrition['carbs']    * multiplier
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


def get_daily_summary(user_id: int, date_str: str = None) -> dict:
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
            'protein':  row[1],
            'fat':      row[2],
            'carbs':    row[3]
        }
    else:
        return {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0}


# --------------------------------
#  Асинхронные хэндлеры (handlers)
# --------------------------------

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_db()
    # При первом запуске запишется DEFAULT_TARGETS
    get_user_targets(user.id)
    await update.message.reply_text(
        f"Привет, {user.first_name}! Я FitoBob, твой фитнес-бот.\n"
        "Я помогу считать калории и макронутриенты.\n"
        "Используй /help для списка команд."
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Список команд FitoBob:\n"
        "/log <еда> <количество> <g|шт> — добавить еду.\n"
        "  Пример: /log яйцо 2 шт\n"
        "           /log рис 150 g\n"
        "/summary — показать, сколько ты сегодня съел и сколько осталось до цели\n"
        "/targets <калории> <белок> <жиры> <угли> — установить свои цели\n"
        "/reset — очистить дневной лог (только сегодня)\n"
        "/help — показать это сообщение"
    )
    await update.message.reply_text(help_text)


async def set_targets_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if len(args) != 4:
        await update.message.reply_text("Использование: /targets <калории> <белок> <жиры> <угли>")
        return

    try:
        cal, prot, fat, carbs = map(int, args)
    except ValueError:
        await update.message.reply_text("Все четыре параметра должны быть целыми числами.")
        return

    new_targets = {
        'calories': cal,
        'protein':  prot,
        'fat':      fat,
        'carbs':    carbs
    }
    set_user_targets(user.id, new_targets)
    await update.message.reply_text(
        f"Цели обновлены: {cal} ккал, {prot} г белка, {fat} г жира, {carbs} г углеводов."
    )


async def log_food_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if len(args) < 3:
        await update.message.reply_text(
            "Использование: /log <еда> <количество> <g|шт>\n"
            "Пример: /log яйцо 2 шт или /log рис 150 g"
        )
        return

    food = args[0].lower()
    try:
        qty = float(args[1])
    except ValueError:
        await update.message.reply_text("Количество должно быть числом. Пример: /log рис 150 g")
        return

    unit = args[2].lower()
    if food not in NUTRITION_DB:
        await update.message.reply_text(
            f"Не знаю продукт '{food}'. Доступные: {', '.join(NUTRITION_DB.keys())}"
        )
        return

    if unit not in ('g', 'шт'):
        await update.message.reply_text("Единица должна быть 'g' или 'шт'. Пример: /log яйцо 2 шт")
        return

    result = log_food_to_db(user.id, food, qty, unit)
    if not result:
        await update.message.reply_text("Не удалось добавить продукт. Проверь название и единицу.")
        return

    cals, prot, fat, carbs = result
    summary = get_daily_summary(user.id)
    targets = get_user_targets(user.id)

    reply = (
        f"Добавлено: {food} {int(qty)}{unit}\n"
        f"⇨ {int(cals)} ккал, {int(prot)} г белка, {int(fat)} г жира, {int(carbs)} г углеводов.\n\n"
        f"Сегодня: {int(summary['calories'])}/{targets['calories']} ккал, "
        f"{int(summary['protein'])}/{targets['protein']} г белка\n"
        f"Жир: {int(summary['fat'])}/{targets['fat']} г, "
        f"Углеводы: {int(summary['carbs'])}/{targets['carbs']} г"
    )
    await update.message.reply_text(reply)


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    summary = get_daily_summary(user.id)
    targets = get_user_targets(user.id)

    reply = (
        f"📋 Ежедневный отчёт ({date.today().isoformat()}):\n"
        f"Калории: {int(summary['calories'])}/{targets['calories']}\n"
        f"Белок: {int(summary['protein'])}/{targets['protein']} г\n"
        f"Жир: {int(summary['fat'])}/{targets['fat']} г\n"
        f"Углеводы: {int(summary['carbs'])}/{targets['carbs']} г"
    )
    await update.message.reply_text(reply)


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = date.today().isoformat()
    c.execute('DELETE FROM food_log WHERE user_id=? AND date=?', (user.id, today))
    conn.commit()
    conn.close()
    await update.message.reply_text("Лог за сегодня очищен.")


async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Не понимаю команду. Используй /help.")


# ---------------------------
#  Основная точка входа main
# ---------------------------

def main():
    # Инициализируем приложение
    application = ApplicationBuilder().token(TOKEN).build()

    # Регистрируем handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("targets", set_targets_handler))
    application.add_handler(CommandHandler("log", log_food_handler))
    application.add_handler(CommandHandler("summary", summary_handler))
    application.add_handler(CommandHandler("reset", reset_handler))

    application.add_handler(
        MessageHandler(filters.COMMAND, unknown_handler)
    )

    # Запускаем поллинг (бот работает в фоне до остановки)
    application.run_polling()


if __name__ == "__main__":
    main()
