# bot.py

import telebot
import datetime
import pytz
import logging
import time
import requests

# --- Библиотеки для API ---
from nhlpy import NHLClient

# --- Планировщик ---
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# --- НАСТРОЙКИ ---
import os
import telebot

BOT_TOKEN = os.environ['BOT_TOKEN']  # читаем токен из переменной окружения
bot = telebot.TeleBot(BOT_TOKEN)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Включаем логирование, чтобы видеть в консоли, что происходит
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- ИНИЦИАЛИЗАЦИЯ ---
# Создаем бота
bot = telebot.TeleBot(BOT_TOKEN)

# Создаем клиента для НХЛ
try:
    nhl_client = NHLClient()
    logger.info("NHL Client успешно создан.")
except Exception as e:
    logger.error(f"Ошибка при создании NHL Client: {e}")
    nhl_client = None

KHL_URL = "https://www.flashscorekz.com/hockey/russia/khl/results/"
KHL_HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

KHL_TEAMS = {
    "Авангард",
    "Автомобилист",
    "Адмирал",
    "Ак Барс",
    "Амур",
    "Барыс",
    "Витязь",
    "Динамо Москва",
    "Динамо Минск",
    "Шанхайские Драконы",
    "Лада",
    "Локомотив",
    "Металлург",
    "Нефтехимик",
    "Салават Юлаев",
    "Северсталь",
    "Сибирь",
    "СКА",
    "Сочи",
    "Спартак Москва",
    "Торпедо",
    "Трактор",
    "ЦСКА",
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def extract_khl_value(block: str, key: str):
    import re
    pattern = rf"{re.escape(key)}÷(.*?)(?:¬|$)"
    match = re.search(pattern, block)
    return match.group(1).strip() if match else None


def parse_khl_match_block(block: str):
    home = extract_khl_value(block, "CX") or extract_khl_value(block, "AE")
    away = extract_khl_value(block, "AF")
    home_score = extract_khl_value(block, "AG")
    away_score = extract_khl_value(block, "AH")
    timestamp = extract_khl_value(block, "AD")

    if not home or not away:
        return None

    if home not in KHL_TEAMS or away not in KHL_TEAMS:
        return None

    if home_score is None or away_score is None:
        return None

    match_data = {
        "home": home,
        "away": away,
        "home_score": home_score,
        "away_score": away_score,
        "timestamp": timestamp,
        "date": None,
        "dt": None,
    }

    if timestamp and timestamp.isdigit():
        dt = datetime.datetime.fromtimestamp(int(timestamp), tz=MOSCOW_TZ)
        match_data["date"] = dt.strftime("%d.%m.%Y %H:%M")
        match_data["dt"] = dt

    return match_data


def fetch_khl_matches():
    response = requests.get(KHL_URL, headers=KHL_HEADERS, timeout=20)
    response.raise_for_status()

    html = response.text
    raw_blocks = html.split("~AA÷")
    matches = []

    for block in raw_blocks:
        match_data = parse_khl_match_block(block)
        if match_data:
            matches.append(match_data)

    unique_matches = []
    seen = set()

    for match in matches:
        key = (
            match["home"],
            match["away"],
            match["timestamp"],
            match["home_score"],
            match["away_score"],
        )
        if key not in seen:
            seen.add(key)
            unique_matches.append(match)

    unique_matches.sort(
        key=lambda x: x["dt"] if x["dt"] else datetime.datetime.min.replace(tzinfo=MOSCOW_TZ),
        reverse=True
    )

    return unique_matches


def get_nhl_scores():
    """
    Получает результаты матчей НХЛ за сегодня.
    Возвращает отформатированную строку для отправки в Telegram.
    """
    if nhl_client is None:
        return "⚠️ Ошибка: Не удалось подключиться к сервису данных НХЛ."

    today_moscow = datetime.datetime.now(MOSCOW_TZ).date()
    date_str = today_moscow.strftime("%Y-%m-%d")

    try:
        logger.info(f"Запрашиваю расписание НХЛ на {date_str}")
        daily_schedule = nhl_client.schedule.daily_schedule(date=date_str)

        if not daily_schedule or 'games' not in daily_schedule or not daily_schedule['games']:
            return f"🏒 НХЛ. Сегодня ({today_moscow.strftime('%d.%m.%Y')}) матчей нет."

        message = f"🏒 **Результаты НХЛ за {today_moscow.strftime('%d.%m.%Y')}**\n\n"
        for game in daily_schedule['games']:
            home_team = game['homeTeam']['abbrev']
            away_team = game['awayTeam']['abbrev']
            home_score = game['homeTeam'].get('score', 0)
            away_score = game['awayTeam'].get('score', 0)
            game_state = game['gameState']

            status_text = ""
            if game_state == 'OFF':
                status_text = "🔴 Финальный счет"
            elif game_state == 'LIVE':
                period = game.get('periodDescriptor', {}).get('number', 1)
                if game.get('gameOutcome', {}).get('lastPeriodType') == 'REG':
                    status_text = f"⏱️ Идет {period}-й период"
                else:
                    status_text = f"⏱️ Идет {period}-й период"
            else:
                status_text = "⏳ Матч еще не начался"

            message += f"{away_team} **{away_score}** : **{home_score}** {home_team}\n"
            message += f"└ {status_text}\n\n"

        return message

    except Exception as e:
        logger.exception("Ошибка при получении данных НХЛ")
        return "⚠️ Произошла ошибка при получении данных НХЛ."


def get_khl_scores():
    """
    Получает результаты матчей КХЛ за сегодня с Flashscore.
    Возвращает отформатированную строку для отправки в Telegram.
    """
    today_moscow = datetime.datetime.now(MOSCOW_TZ).date()

    try:
        logger.info("Запрашиваю данные КХЛ с Flashscore")
        matches = fetch_khl_matches()

        if not matches:
            return f"🇷🇺 **Результаты КХЛ за {today_moscow.strftime('%d.%m.%Y')}**\n\nМатчи не найдены."

        today_matches = []
        for match in matches:
            if match["dt"] and match["dt"].date() == today_moscow:
                today_matches.append(match)

        if not today_matches:
            return f"🇷🇺 **Результаты КХЛ за {today_moscow.strftime('%d.%m.%Y')}**\n\nСегодня матчей не найдено."

        message = f"🇷🇺 **Результаты КХЛ за {today_moscow.strftime('%d.%m.%Y')}**\n\n"

        for match in today_matches:
            message += (
                f"{match['away']} **{match['away_score']}** : **{match['home_score']}** {match['home']}\n"
                f"└ 🔴 Финальный счет\n\n"
            )

        return message

    except Exception as e:
        logger.exception("Ошибка при получении данных КХЛ")
        return "⚠️ Произошла ошибка при получении данных КХЛ."

# --- ОБРАБОТЧИКИ КОМАНД ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот с результатами матчей КХЛ и НХЛ.\n"
                           "Я автоматически присылаю результаты:\n"
                           "🇷🇺 КХЛ в 23:00 по Москве\n"
                           "🇺🇸 НХЛ в 10:00 по Москве\n"
                           "Используй команды /nhl или /khl, чтобы получить результаты сейчас.")

@bot.message_handler(commands=['nhl'])
def send_nhl_now(message):
    bot.send_message(message.chat.id, "Запрашиваю данные по НХЛ...")
    result = get_nhl_scores()
    bot.send_message(message.chat.id, result, parse_mode='Markdown')

@bot.message_handler(commands=['khl'])
def send_khl_now(message):
    bot.send_message(message.chat.id, "Запрашиваю данные по КХЛ...")
    result = get_khl_scores()
    bot.send_message(message.chat.id, result, parse_mode='Markdown')

# --- ФУНКЦИИ ДЛЯ ПЛАНИРОВЩИКА ---
def scheduled_nhl():
    logger.info("Запуск запланированной отправки НХЛ")
    result = get_nhl_scores()
    logger.info(f"Результат для отправки: {result}")
    pass

def scheduled_khl():
    logger.info("Запуск запланированной отправки КХЛ")
    result = get_khl_scores()
    logger.info(f"Результат для отправки: {result}")
    pass

# --- ЗАПУСК ---
if __name__ == '__main__':
    logger.info("Бот запускается...")

    scheduler = BackgroundScheduler(timezone=MOSCOW_TZ)

    scheduler.add_job(scheduled_nhl, CronTrigger(hour=10, minute=0, timezone=MOSCOW_TZ))
    scheduler.add_job(scheduled_khl, CronTrigger(hour=23, minute=0, timezone=MOSCOW_TZ))

    scheduler.start()
    logger.info("Планировщик запущен.")

    logger.info("Бот начал опрос Telegram...")
    bot.infinity_polling()