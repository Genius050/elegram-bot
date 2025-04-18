import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import os
from dotenv import load_dotenv
import asyncio
import aiohttp
import tempfile
import vk_api
import json
import signal
from pathlib import Path
import requests
import re
from fuzzywuzzy import fuzz
import lyricsgenius

# Загружаем переменные окружения
load_dotenv()

# Настраиваем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение токена бота
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не найден в переменных окружения")
    raise ValueError("TELEGRAM_BOT_TOKEN не найден в переменных окружения")

# Создание приложения
application = Application.builder().token(TOKEN).build()

# Инициализируем VK API
def init_vk():
    try:
        token = os.getenv('VK_TOKEN')
        logger.info(f"Пытаемся получить токен VK: {token[:20]}..." if token else "Токен не найден")
        
        if not token:
            logger.error("Отсутствует токен VK!")
            return None
            
        vk_session = vk_api.VkApi(
            token=token,
            app_id=2685278,
            client_secret='hHbJug59sKJie78wjrH8',
            api_version='5.199'
        )
        
        vk_session.http.headers.update({
            'User-Agent': 'KateMobileAndroid/56 lite-460 (Android 4.4.2; SDK 19; x86; unknown Android SDK built for x86; en)',
            'X-Kate-MobileClient': '1'
        })
        
        vk = vk_session.get_api()
        
        try:
            test = vk.audio.search(q="test", count=1)
            logger.info("VK авторизация успешна через Kate Mobile")
            return vk
            
        except Exception as e:
            logger.error(f"Нет доступа к аудио: {e}")
            logger.exception(e)
            return None
            
    except Exception as e:
        logger.error(f"Ошибка инициализации VK: {e}")
        logger.exception(e)
        return None

# Глобальная переменная для VK API
vk = init_vk()

async def search_track(query, expected_title=None, expected_artist=None):
    try:
        logger.info(f"Поиск трека: {query}")
        
        if not vk:
            logger.error("VK API не инициализирован")
            return []
        
        search_results = await asyncio.to_thread(vk.audio.search, q=query, count=10, sort=2, v='5.199')
        
        logger.info(f"Результаты поиска: {search_results}")
        
        results = []
        if search_results and 'items' in search_results:
            tasks = []
            for item in search_results['items']:
                tasks.append(process_item(item, expected_title, expected_artist))
            
            results = await asyncio.gather(*tasks)
            results = [result for result in results if result]
            
        logger.info(f"Всего найдено треков: {len(results)}")
        return results
    except Exception as e:
        logger.error(f"Ошибка при поиске трека: {e}")
        return []

async def process_item(item, expected_title, expected_artist):
    try:
        item_title = item['title'].strip().lower()
        item_artist = item['artist'].strip().lower()
        expected_title_clean = expected_title.strip().lower() if expected_title else None
        expected_artist_clean = expected_artist.strip().lower() if expected_artist else None

        title_match = fuzz.partial_ratio(expected_title_clean, item_title) > 70 if expected_title_clean else True
        artist_match = fuzz.partial_ratio(expected_artist_clean, item_artist) > 70 if expected_artist_clean else True

        if title_match and artist_match:
            audio_info = await asyncio.to_thread(vk.audio.getById, audios=f"{item['owner_id']}_{item['id']}")
            
            if audio_info and len(audio_info) > 0:
                url = audio_info[0].get('url')
                if url:
                    logger.info(f"Найден трек: {item['artist']} - {item['title']}")
                    return {
                        "title": f"{item['artist']} - {item['title']}",
                        "url": url,
                        "duration": item['duration']
                    }
    except Exception as e:
        logger.error(f"Ошибка при обработке трека: {e}")
    
    return None

async def download_audio(track):
    try:
        logger.info(f"Скачивание аудио: {track['title']} с {track['url']}")
        async with aiohttp.ClientSession() as session:
            async with session.get(track['url'], timeout=30) as response:
                if response.status == 200:
                    content = await response.read()
                    logger.info(f"Скачан файл размером: {len(content)} байт")
                    return content
                else:
                    logger.error(f"Ошибка при скачивании: {response.status}")
                    return None
    except asyncio.TimeoutError:
        logger.error("Таймаут при скачивании аудио")
        return None
    except Exception as e:
        logger.error(f"Ошибка при скачивании аудио: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Я бот для поиска музыки. Используйте команды:\n/help - помощь\nПоиск по названию - для поиска по названию трека\nПоиск по тексту - для поиска по тексту песни', reply_markup=show_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Вот список доступных команд:\n/start - Начать работу\n/help - Показать справку\nПоиск по названию - искать музыку по названию\nПоиск по тексту - искать музыку по тексту песни', reply_markup=show_main_keyboard())

def show_main_keyboard():
    keyboard = [
        ["Поиск по названию"],
        ["Поиск по тексту"],
        ["Избранное"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def search_lyrics(query):
    logger.info(f"Поиск текста через Genius API: {query}")
    token = os.getenv('GENIUS_API_TOKEN')
    if not token:
        logger.error("GENIUS_API_TOKEN не найден")
        return []

    try:
        genius = lyricsgenius.Genius(token)
        search_results = genius.search_songs(query)
        
        tracks = []
        if search_results and 'hits' in search_results:
            for hit in search_results['hits']:
                if 'result' in hit:
                    result = hit['result']
                    search_query = f"{result.get('artist_names', '')} {result.get('title', '')}"
                    
                    vk_tracks = await search_track(search_query)
                    if vk_tracks:
                        vk_track = vk_tracks[0]
                        track = {
                            'title': f"{result.get('artist_names', '')} - {result.get('title', '')}",
                            'url': vk_track['url'],
                            'duration': vk_track['duration']
                        }
                        tracks.append(track)
                        logger.info(f"Найден трек: {track['title']}")
        
        logger.info(f"Найдено {len(tracks)} результатов на Genius.")
        return tracks
    except Exception as e:
        logger.error(f"Ошибка при поиске текста: {str(e)}")
        return []

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.message.text.strip()
        logger.info(f"Получен текстовый запрос: {query}")
        
        search_type = context.user_data.get('search_type', None)
        logger.info(f"Текущий тип поиска: {search_type}")

        if query.lower() in ["поиск по названию", "поиск по тексту", "избранное"]:
            logger.info("Сбрасываем тип поиска")
            context.user_data['search_type'] = None

        if search_type is None:
            if query.lower() == "поиск по названию":
                context.user_data['search_type'] = 'title'
                await update.message.reply_text("🔍 Поиск по названию. Введите название песни и (опционально) исполнителя через запятую.", reply_markup=show_main_keyboard())
                return
            
            if query.lower() == "поиск по тексту":
                context.user_data['search_type'] = 'lyrics'
                await update.message.reply_text("Готов искать по тексту. Введите текст песни.", reply_markup=show_main_keyboard())
                return
            
            if query.lower() == "избранное":
                await show_favorites(update, context)
                return
            
            await update.message.reply_text("Выберите тип поиска:", reply_markup=show_main_keyboard())
            return

        if search_type == 'title':
            logger.info(f"Поиск треков по названию: {query}")
            try:
                tracks = await search_tracks(query)
                if tracks:
                    context.user_data['tracks'] = tracks
                    await show_tracks(update, context, tracks)
                else:
                    await update.message.reply_text("😔 Не удалось найти трек. Попробуйте другой.", reply_markup=show_main_keyboard())
                
                context.user_data['search_type'] = None
                return
            
            except Exception as e:
                logger.error(f"Ошибка при поиске треков: {e}")
                await update.message.reply_text("😔 Произошла ошибка при поиске треков.", reply_markup=show_main_keyboard())
                return

        if search_type == 'lyrics':
            logger.info(f"Поиск текста песен: {query}")
            try:
                lyrics_results = await search_lyrics(query)
                if lyrics_results:
                    logger.info(f"Найдено {len(lyrics_results)} результатов на Genius.")
                    await show_tracks(update, context, lyrics_results)
                else:
                    await update.message.reply_text("😔 Не удалось найти текст песни. Попробуйте другой запрос.", reply_markup=show_main_keyboard())
            except Exception as e:
                logger.error(f"Ошибка при поиске текста: {e}")
                await update.message.reply_text("😔 Произошла ошибка при поиске текста.", reply_markup=show_main_keyboard())
            finally:
                context.user_data['search_type'] = None
            return

    except Exception as e:
        logger.error(f"Ошибка при обработке текстового сообщения: {e}")
        await update.message.reply_text("😔 Произошла ошибка. Попробуйте позже.", reply_markup=show_main_keyboard())

async def show_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE, tracks):
    context.user_data['tracks'] = tracks
    keyboard = []
    for i, track in enumerate(tracks):
        keyboard.append([
            InlineKeyboardButton(track['title'], callback_data=f"play_{i}"),
            InlineKeyboardButton("⭐ Добавить в избранное", callback_data=f"add_favorite_{i}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите трек:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"Получен запрос на кнопку: {query.data}")
    
    user_id = str(update.effective_user.id)

    if query.data.startswith("play_") or query.data.startswith("download_"):
        track_index = int(query.data.split("_")[1])
        favorites = load_favorites()
        
        if query.data.startswith("play_"):
            tracks = context.user_data.get('tracks', [])
            if not tracks or track_index >= len(tracks):
                await query.answer("Трек не найден.")
                return
            track = tracks[track_index]
        else:
            if user_id not in favorites or track_index >= len(favorites[user_id]):
                await query.answer("Трек не найден в избранном.")
                return
            track = favorites[user_id][track_index]
            
        content = await download_audio(track)
        if content:
            await query.message.reply_audio(audio=content, title=track['title'])
        else:
            await query.message.reply_text("😔 Не удалось скачать трек.")

# Добавляем обработчики
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(CallbackQueryHandler(button_callback))

# Функция для обработки вебхуков
async def handler(request):
    try:
        if request.method == 'GET':
            return {
                'statusCode': 200,
                'body': 'Telegram Bot is running!'
            }
        
        if request.method == 'POST':
            try:
                body = await request.body()
                if not body:
                    logger.error("Пустое тело запроса")
                    return {
                        'statusCode': 400,
                        'body': json.dumps({'error': 'Empty request body'})
                    }
                
                data = json.loads(body)
                logger.info(f"Получен POST запрос с данными: {data}")
                
                update = Update.de_json(data, application.bot)
                await application.process_update(update)
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({'status': 'ok'})
                }
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка декодирования JSON: {e}")
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'Invalid JSON'})
                }
            except Exception as e:
                logger.error(f"Ошибка при обработке POST запроса: {e}")
                return {
                    'statusCode': 500,
                    'body': json.dumps({'error': str(e)})
                }
        
        return {
            'statusCode': 405,
            'body': 'Method Not Allowed'
        }
    except Exception as e:
        logger.error(f"Общая ошибка при обработке запроса: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        } 