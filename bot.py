# bot.py

import os
import logging
import sqlite3
import json
import re
import difflib
from datetime import date

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ------------------------
#    ЛОГИРОВАНИЕ
# ------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------
#   КОНФИГУРАЦИЯ
# ------------------------
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
# Ключи хранятся в нижнем регистре. Добавьте сюда любые русские названия, которые часто вводите.
NUTRITION_DB = {
    'яйцо':     {'calories': 155, 'protein': 13,  'fat': 11,  'carbs': 1.1},
    'яйца':     {'calories': 155, 'protein': 13,  'fat': 11,  'carbs': 1.1},
    'рис':      {'calories': 130, 'protein': 2.7, 'fat': 0.3, 'carbs': 28},
    'курица':   {'calories': 165, 'protein': 31,  'fat': 3.6, 'carbs': 0},
    'говядина': {'calories': 250, 'protein': 26,  'fat': 17,  'carbs': 0},
    'яблоко':   {'calories': 52,  'protein': 0.3, 'fat': 0.2, 'carbs': 14},
    'банан':    {'calories': 89,  'protein': 1.1, 'fat': 0.3, 'carbs': 23},
    'брокколи': {'calories': 55,  'protein': 3.7, 'fat': 0.6, 'carbs': 11},
    'лосось':   {'calories': 208, 'protein': 20,  'fat': 13,  'carbs': 0},
    'миндаль':  {'calories': 579, 'protein': 21,  'fat': 50,  'carbs': 22},
    'протеин':  {'calories': 110, 'protein': 20,  'fat': 1,   'carbs': 3},
    'панель':   {'calories': 350, 'protein': 5,   'fat': 15,  'carbs': 50},  # пример торта
    'арбуз':    {'calories': 30,  'protein': 0.6, 'fat': 0.2, 'carbs': 8},
    'свинина':  {'calories': 300, 'protein': 25,  'fat': 20,  'carbs': 0},
    'суп':      {'calories': 30,  'protein': 2,   'fat': 1,   'carbs': 3},
}


# ------------------------------
#  Функции работы с базой данных
# ------------------------------

def init_db():
    """
    Создаёт таблицы users (для хранения целей) и food_log (для логов еды), если их ещё нет.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            targets TEXT
        )
    ''')
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
    c.execute('REPLACE INTO users (user_id, targets) VALUES (?, ?)', (user_id, targets_json))
    conn.commit()
    conn.close()


def log_food_to_db(user_id: int, food_name: str, qty: float, diet_unit: str):
    """
    Записывает в базу одну позицию: food_name (точное название из NUTRITION_DB),
    количество qty и единицы (g или шт). Возвращает (calories, protein, fat, carbs).
    Если food_name нет в базе — возвращает None.
    """
    nutrition = NUTRITION_DB.get(food_name)
    if not nutrition:
        return None

    # Если единица 'g' → qty грамм, если 'шт' → считаем 1 шт = 50 г
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
    ''', (user_id, food_name, qty, diet_unit, calories, protein, fat, carbs, date_str))
    conn.commit()
    conn.close()
    return calories, protein, fat, carbs


def get_daily_summary(user_id: int, date_str: str = None) -> dict:
    """
    Возвращает суммы калорий, белков, жиров, углеводов за дату date_str (по ISO-формату).
    Если date_str не передан, берётся сегодня.
    """
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


# ----------------------------------------
#  Утилиты: парсинг свободного текста «как AI»
# ----------------------------------------

# Список всех ключей NUTRITION_DB (массив строк), для фаззи-матчинга
ALL_FOODS = list(NUTRITION_DB.keys())

def find_closest_food(name: str) -> str | None:
    """
    Фаззи-подбор: находит самый близкий ключ из NUTRITION_DB для переданного name.
    Возвращает найденное название (точно из базы) либо None, если нет похожих.
    """
    # Убираем лишние пробелы и приводим к нижнему регистру
    clean = name.strip().lower()
    # difflib.get_close_matches вернёт список похожих слов (нестрогое сравнение)
    matches = difflib.get_close_matches(clean, ALL_FOODS, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    else:
        return None


def parse_food_entries(text: str) -> list[tuple[str, float, str]]:
    """
    Парсит текст, где может быть несколько позиций еды, и пытается выделить из каждой:
      - название (возможны ошибки),
      - количество (цифры, возможно с плавающей точкой),
      - единицу (g, гр, грамм, шт, штук).
    Возвращает список кортежей (food_corrected_name, qty, unit), 
    где food_corrected_name точно совпадает с ключом из NUTRITION_DB.
    """
    results: list[tuple[str, float, str]] = []
    # Разделим по запятым, точкам с запятой или переносам строки
    # Учтём, что пользователь может писать: "яйцо2шт", "рис 150g", "банан 1 шт"
    parts = re.split(r'[,\n;]+', text)

    for part in parts:
        part = part.strip().lower()
        if not part:
            continue

        # Ищем шаблон: [буквы и пробелы] [число] [буквы]
        # Возможные единицы: g, гр, грамм*, шт, штук*. 
        # Сделаем ленивый поиск: сначала найдём число и единицу, а всё до него - название.
        m = re.search(r'([^\d]+?)\s*([\d\.]+)\s*(грамм|гр|g|шт|штук|шт\.)?$', part)
        if m:
            name_part = m.group(1).strip()
            qty_part = m.group(2)
            unit_raw = m.group(3) or ''
            # Нормализуем единицу
            if unit_raw.startswith('г'):
                unit = 'g'
            elif unit_raw.startswith('g'):
                unit = 'g'
            else:
                # всё, что не «г», считаем «шт»
                unit = 'шт'

            try:
                qty = float(qty_part.replace(',', '.'))
            except ValueError:
                continue

            # Фаззи-подбор названия
            match_food = find_closest_food(name_part)
            if match_food:
                results.append((match_food, qty, unit))
            else:
                # не нашли похожего товара — пропускаем
                continue
        else:
            # Если не подошёл шаблон с количеством, 
            # возможно, пользователь написал только имя (без числа/единицы).
            # В этом случае считаем, что qty = 1 «шт» и попробуем фаззи-подбор:
            possible_name = part.strip()
            match_food = find_closest_food(possible_name)
            if match_food:
                # qty = 1 шт
                results.append((match_food, 1.0, 'шт'))
            else:
                continue

    return results


# --------------------------------
#   Асинхронные хэндлеры (handlers)
# --------------------------------

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_db()
    # При первом старте создастся запись в users с DEFAULT_TARGETS (за счёт get_user_targets)
    get_user_targets(user.id)
    await update.message.reply_text(
        f"Привет, {user.first_name}! Я FitoBob, твой фитнес-бот.\n"
        "Теперь можно просто писать мне, что и сколько вы съели, например:\n"
        "  • яйцо 2 шт, рис 150г, банан\n"
        "Или даже с ошибками в написании — я найду похожие продукты автоматически.\n"
        "Чтобы посмотреть, что вы уже съели за сегодня, напишите «сводка» или отправьте /summary.\n"
        "Чтобы изменить цели, используйте /targets <калории> <белок> <жиры> <углеводы>.\n"
        "Подробнее по командам: /help"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🌟 Список команд FitoBob:\n\n"
        "/start — перезапустить бота (всё заново создастся в базе)\n"
        "/help — показать это сообщение\n"
        "/summary — показать, сколько вы сегодня съели и сколько осталось до целей\n"
        "/targets <калории> <белок> <жиры> <углеводы> — установить свои цели\n"
        "/reset — очистить дневной лог (удаляет только то, что было сегодня)\n\n"
        "📌 Но необязательно пользоваться командами! Просто пишите мне, что и сколько вы съели:\n"
        "  • «я съел яйцо 2шт, рис 150 г, банан 1 шт»\n"
        "  • «5 позиций: яйцо2 шт; рис150г; банан1шт; протеин 30; яблоко»\n"
        "Я автоматически разберу ваше сообщение, даже если где-то допущена опечатка.\n"
    )
    await update.message.reply_text(help_text)


async def set_targets_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if len(args) != 4:
        await update.message.reply_text("Использование: /targets <калории> <белок> <жиры> <углеводы>")
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
        f"✅ Цели обновлены:\n"
        f"  • Калории: {cal} ккал\n"
        f"  • Белок: {prot} г\n"
        f"  • Жиры: {fat} г\n"
        f"  • Углеводы: {carbs} г"
    )


async def log_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Основной хэндлер для текстовых сообщений (не команд). 
    Пытается распарсить до нескольких позиций еды и залогировать их.
    Если в тексте есть слова 'сводка', 'итог', 'итоге', 'сколько', то покажет summary.
    """
    user = update.effective_user
    text = update.message.text.strip().lower()

    # Если пользователь хочет просто сводку:
    if re.search(r'\b(сводка|итог|итоге|сколько)\b', text):
        # Вызовем summary
        return await summary_handler(update, context)

    # Парсим текст на позиции еды
    entries = parse_food_entries(text)
    if not entries:
        # Не удалось распознать ни одной позиции
        await update.message.reply_text(
            "❌ Не удалось найти продукты в этом сообщении.\n"
            "Попробуйте написать так: «я съел яйцо 2шт, рис 150 г».\n"
            "Или /help для списка команд."
        )
        return

    # Логируем все найденные позиции по очереди
    added_lines = []
    for food_name, qty, unit in entries:
        result = log_food_to_db(user.id, food_name, qty, unit)
        if result:
            cals, prot, fat, carbs = result
            # Например: "яйцо 2шт → 310 ккал, 26г белка"
            added_lines.append(
                f"{food_name} {int(qty)}{unit} → {int(cals)} ккал, {int(prot)}г белка"
            )

    # Собираем ответ для пользователя
    if not added_lines:
        await update.message.reply_text(
            "❌ Не удалось добавить ни одного продукта. Проверьте, доступны ли они в базе."
        )
        return

    # Получаем общий дневной итог после добавления
    summary = get_daily_summary(user.id)
    targets = get_user_targets(user.id)

    reply_text = "✅ Добавлено:\n" + "\n".join(f"  • {line}" for line in added_lines) + "\n\n"
    reply_text += (
        f"📋 Сегодня всего:\n"
        f"  • Калории: {int(summary['calories'])}/{targets['calories']} ккал\n"
        f"  • Белок: {int(summary['protein'])}/{targets['protein']} г\n"
        f"  • Жиры: {int(summary['fat'])}/{targets['fat']} г\n"
        f"  • Углеводы: {int(summary['carbs'])}/{targets['carbs']} г\n"
    )
    await update.message.reply_text(reply_text)


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    summary = get_daily_summary(user.id)
    targets = get_user_targets(user.id)

    reply = (
        f"📋 Ежедневный отчёт ({date.today().isoformat()}):\n"
        f"  • Калории: {int(summary['calories'])}/{targets['calories']} ккал\n"
        f"  • Белок: {int(summary['protein'])}/{targets['protein']} г\n"
        f"  • Жиры: {int(summary['fat'])}/{targets['fat']} г\n"
        f"  • Углеводы: {int(summary['carbs'])}/{targets['carbs']} г\n"
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
    await update.message.reply_text("🔄 Лог за сегодня очищён.")


async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Не понимаю команду. Используй /help.")


# ---------------------------
#  Основная точка входа main
# ---------------------------

def main():
    # Создаём приложение
    application = ApplicationBuilder().token(TOKEN).build()

    # Командные хэндлеры
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("targets", set_targets_handler))
    application.add_handler(CommandHandler("summary", summary_handler))
    application.add_handler(CommandHandler("reset", reset_handler))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_handler))

    # Хэндлер свободного текста — отсеиваем команды через previous handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_text_handler))

    # Запускаем поллинг
    application.run_polling()


if __name__ == "__main__":
    main()
