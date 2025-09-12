# -*- coding: utf-8 -*-
import time
import random
import json
from datetime import datetime, timedelta
from collections import Counter
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
import threading
import os
import subprocess
import sys
import requests
import asyncio

# === Загружаем токен из Secrets ===
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("? ОШИБКА: BOT_TOKEN не найден в Secrets. Проверь настройки!")
    exit()

DATA_FILE = "users.json"

# === Комментарии ===
COMMENTS = {
    "simple": [
        "Это легкотня!",
        "Просто как дважды два!",
        "Ну это совсем просто!",
        "А тут и думать не нужно!"
    ],
    "hard": [
        "О! Это посложнее…",
        "Тут нужно подумать!",
        "С таким справишься?",
        "А такой?"
    ],
    "normal": [
        "Далее!",
        "Еще!",
        "Следующий!"
    ]
}

# === Работа с данными ===
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for user_id in data:
            if "attempts" in data[user_id]:
                for attempt in data[user_id]["attempts"]:
                    if "date" not in attempt:
                        attempt["date"] = "2000-01-01 00:00"
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"? Ошибка сохранения: {e}")

def parse_question(q):
    if ' ? ' in q:
        a, b = q.split(' ? ')
        return int(a), '*', int(b)
    elif ' ? ' in q:
        a, b = q.split(' ? ')
        return int(a), '/', int(b)

def is_simple_question(a, op, b):
    if op == '*':
        return a == 1 or b == 1 or a == 2 or b == 2 or a == 10 or b == 10
    else:
        return b == 1 or b == 2 or b == 10 or (a == b and a != 0)

def is_hard_question(a, op, b):
    if op == '*':
        return 6 <= a <= 9 and 6 <= b <= 9
    else:
        if b == 0:
            return False
        if a % b != 0:
            return False
        quotient = a // b
        return 6 <= b <= 9 and 6 <= quotient <= 9

def generate_unique_pairs():
    seen = set()
    simple_pairs = []
    hard_pairs = []
    normal_pairs = []

    for a in range(1, 11):
        for b in range(1, 11):
            key_mul = tuple(sorted([a, b]))
            if key_mul not in seen:
                seen.add(key_mul)

                if is_simple_question(a, '*', b):
                    simple_pairs.append((a, b, '*'))
                elif is_hard_question(a, '*', b):
                    hard_pairs.append((a, b, '*'))
                else:
                    normal_pairs.append((a, b, '*'))

                c = a * b
                if is_simple_question(c, '/', b):
                    simple_pairs.append((c, b, '/'))
                elif is_hard_question(c, '/', b):
                    hard_pairs.append((c, b, '/'))
                else:
                    normal_pairs.append((c, b, '/'))

    random.shuffle(simple_pairs)
    random.shuffle(hard_pairs)
    random.shuffle(normal_pairs)

    selected = simple_pairs[:3] + hard_pairs[:10]
    remaining = 20 - len(selected)
    selected.extend(normal_pairs[:remaining])
    random.shuffle(selected)

    questions = []
    for item in selected:
        if item[2] == '*':
            questions.append((f"{item[0]} ? {item[1]}", item[0] * item[1]))
        elif item[2] == '/':
            questions.append((f"{item[0]} ? {item[1]}", item[0] // item[1]))
    return questions

# === Обработчики ===
async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, idx):
    questions = context.user_data['questions']
    question, answer = questions[idx]
    a, op, b = parse_question(question)
    is_simple = is_simple_question(a, op, b)
    is_hard = is_hard_question(a, op, b)
    comment_type = "simple" if is_simple else "hard" if is_hard else "normal"

    use_comment = False
    if context.user_data['comments_used'] < 7:
        if random.random() < 0.5:
            use_comment = True

    text = ""
    if use_comment:
        comment = random.choice(COMMENTS[comment_type])
        text += f"{comment}\n\n"
        context.user_data['comments_used'] += 1

    if idx in context.user_data.get('skipped', []):
        text += "?? *Пропущенный вопрос*\n\n"

    text += f"Вопрос {idx + 1}: {question}"

    await update.message.reply_text(
        text,
        reply_markup=ReplyKeyboardMarkup([["Пропустить"]], one_time_keyboard=True, resize_keyboard=True),
        parse_mode='Markdown'
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    data = load_data()
    if user_id not in data:
        data[user_id] = {
            "attempts": [],
            "best_time": float('inf'),
            "worst_time": 0,
            "total_tests": 0,
            "frequent_errors": {}
        }
        save_data(data)
    keyboard = [["Да", "Нет"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        f"Привет, {user_name}! ??\n\n"
        "Я создан, чтобы сделать из тебя умныша по умножению! ???\n\n"
        "Задам тебе 20 примеров. Готов?",
        reply_markup=reply_markup
    )

async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "Да":
        phrases = [
            "Ого, какая тяга к знаниям! ??",
            "Ничего себе, давай попробуем! ??",
            "Ну давай! Поехали!!! ??"
        ]
        await update.message.reply_text(random.choice(phrases), reply_markup=ReplyKeyboardRemove())
        await start_test(update, context)
    elif text == "Нет":
        await update.message.reply_text("А я всё равно задам! Время пошло! ??", reply_markup=ReplyKeyboardRemove())
        await start_test(update, context)

async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = generate_unique_pairs()
    context.user_data['questions'] = questions
    context.user_data['current'] = 0
    context.user_data['correct'] = 0
    context.user_data['start_time'] = time.time()
    context.user_data['errors'] = []
    context.user_data['skipped'] = []
    context.user_data['answered'] = set()
    context.user_data['comments_used'] = 0
    await send_question(update, context, 0)

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'questions' not in context.user_data:
        return

    if update.message.text.strip().lower() == "пропустить":
        current_idx = context.user_data['current']
        context.user_data['skipped'].append(current_idx)
        await ask_next_question(update, context)
        return

    questions = context.user_data['questions']
    idx = context.user_data['current']
    try:
        user_answer = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Введите число!")
        return

    question, correct_answer = questions[idx]
    if user_answer == correct_answer:
        context.user_data['correct'] += 1
    else:
        context.user_data['errors'].append(question)

    context.user_data['answered'].add(idx)
    await ask_next_question(update, context)

async def ask_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = context.user_data['questions']
    current_idx = context.user_data['current']
    next_idx = current_idx + 1

    if next_idx < len(questions) and next_idx not in context.user_data['answered']:
        context.user_data['current'] = next_idx
        await send_question(update, context, next_idx)
        return

    if context.user_data['skipped']:
        skip_idx = context.user_data['skipped'].pop(0)
        context.user_data['current'] = skip_idx
        await send_question(update, context, skip_idx)
        return

    total_time = round(time.time() - context.user_data['start_time'])
    correct = context.user_data['correct']
    user_id = str(update.effective_user.id)
    data = load_data()

    error_questions = context.user_data['errors']
    attempt_data = {
        "correct": correct,
        "time": total_time,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "errors": error_questions
    }
    data[user_id]["attempts"].append(attempt_data)

    data[user_id]["total_tests"] += 1
    if total_time < data[user_id]["best_time"]:
        data[user_id]["best_time"] = total_time
    if total_time > data[user_id]["worst_time"]:
        data[user_id]["worst_time"] = total_time

    save_data(data)

    def format_time(seconds):
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}" if m > 0 else f"{s} сек"

    result = f"? {correct}/20 за {format_time(total_time)}\n\n"
    result += "?? Отлично! Нет ошибок!" if not context.user_data['errors'] else "? Ошибки:\n"
    for q in context.user_data['errors']:
        a, op, b = parse_question(q)
        correct_answer = a * b if op == '*' else a // b
        result += f"  {q} > Правильно: {correct_answer}\n"

    keyboard = [["Еще разок"], ["Общая статистика"], ["Статистика за день"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(result, reply_markup=reply_markup)

async def cmd_stat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    if user_id not in data or not data[user_id]["attempts"]:
        await update.message.reply_text("Сначала пройдите тест!")
        return

    attempts = data[user_id]["attempts"]
    valid_attempts = [a for a in attempts if "date" in a]
    if not valid_attempts:
        await update.message.reply_text("Нет данных с датой.")
        return

    times = [a["time"] for a in valid_attempts]
    best = min(valid_attempts, key=lambda x: x["time"])
    worst = max(valid_attempts, key=lambda x: x["time"])
    avg = sum(times) // len(times)

    one_week_ago = datetime.now() - timedelta(days=7)
    recent_errors = [err for a in valid_attempts for err in a["errors"]
                     if datetime.strptime(a["date"], "%Y-%m-%d %H:%M") >= one_week_ago]
    error_count = Counter(recent_errors).most_common(3)
    error_text = "\n".join([f"{err} > {cnt} раз" for err, cnt in error_count]) if error_count else "нет данных"

    def format_time(seconds):
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}" if m > 0 else f"{s}"

    await update.message.reply_text(
        f"?? Общая статистика:\n"
        f"?? Лучшее: {format_time(best['time'])} ({best['date']})\n"
        f"?? Худшее: {format_time(worst['time'])} ({worst['date']})\n"
        f"?? Среднее: {format_time(avg)}\n\n"
        f"?? Частые ошибки (последние 7 дней):\n{error_text}"
    )

async def cmd_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    if user_id not in data or not data[user_id]["attempts"]:
        await update.message.reply_text("Сначала пройдите тест!")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    todays_attempts = [a for a in data[user_id]["attempts"] if a["date"].startswith(today)]

    if not todays_attempts:
        await update.message.reply_text("Сегодня тесты не проходились.")
        return

    def format_time(seconds):
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}" if m > 0 else f"{s}"

    text_msg = f"?? Статистика за сегодня ({today}):\n\n"
    text_msg += f"Пройдено тестов: {len(todays_attempts)}\n\n"
    for i, a in enumerate(todays_attempts, 1):
        errors = ", ".join(a["errors"]) if a["errors"] else "нет"
        text_msg += f"Попытка {i} ({format_time(a['time'])}):\n  Ошибки: {errors}\n\n"

    await update.message.reply_text(text_msg)

async def handle_after_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "Еще разок":
        await start_test(update, context)
    elif text == "Общая статистика":
        await cmd_stat(update, context)
    elif text == "Статистика за день":
        await cmd_day(update, context)

# === Веб-сервер для keep-alive ===
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "?? Бот работает! Готов к умножению!"

def run_flask():
    app_flask.run(host='0.0.0.0', port=8080)

# Запускаем веб-сервер в фоне
threading.Thread(target=run_flask, daemon=True).start()

# === ?? СТРАХОВКА: бот будит себя каждые 4 минуты ===
import threading
import time
import requests

def keep_awake():
    url = "https://second.sheav1.repl.co"  # ?? Жёстко заданная ссылка
    print(f"?? Будильник запущен: {url}")
    while True:
        try:
            response = requests.get(url, timeout=10)
            print(f"? Пробуждение: {response.status_code} — {url}")
        except Exception as e:
            print(f"? Ошибка подключения: {e}")
        time.sleep(240)  # каждые 4 минуты

# Запускаем в фоне
threading.Thread(target=keep_awake, daemon=True).start()
# === Запуск бота ===
def run_bot():
    try:
        application = Application.builder().token(TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stat", cmd_stat))
        application.add_handler(CommandHandler("day", cmd_day))
        application.add_handler(MessageHandler(filters.Regex("^(Да|Нет)$"), handle_response))
        application.add_handler(MessageHandler(
            filters.Regex("^(Еще разок|Общая статистика|Статистика за день)$"),
            handle_after_test
        ))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))

        # Создаём новый event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(application.run_polling())
        print("?? Бот запущен и получает обновления...")

    except Exception as e:
        print(f"? Ошибка при запуске бота: {e}")

# === Запуск ===
if __name__ == "__main__":
    run_bot()
    print("? Бот работает 24/7. Не закрывайте вкладку.")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("Бот остановлен")
