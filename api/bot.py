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

# Добавляем обработчики
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(CallbackQueryHandler(button_callback))

# Инициализируем VK API
def init_vk():
    try:
        token = os.getenv('vk1.a.dXxAUa9TOQTmNePJEby9zYU0nHyOUmg3LCljYoiyDaqXxvTtkjy0pa59frpY73AJkffiE7qZLn79-wS9kSONvEMyCNFsOZYh1d0GLoPeYPYq0CsHNxaWNoRfTbsQxrkOPYOLMVgvXJoQNvkT_n7G0C-j2P40MVmFRV3xSwdRDRwOZkXYNA0RYLrVDrF-OFoOgtGGsfoiN2_KEtoDoNY8zg')
        logger.info(f"Пытаемся получить токен VK: {token[:20]}..." if token else "Токен не найден")
        
        if not token:
            logger.error("Отсутствует токен VK!")
            return None
            
        # Используем Kate Mobile
        vk_session = vk_api.VkApi(
            token=token,
            app_id=2685278,  # Kate Mobile app_id
            client_secret='hHbJug59sKJie78wjrH8',
            api_version='5.199'
        )
        
        # Устанавливаем заголовки Kate Mobile
        vk_session.http.headers.update({
            'User-Agent': 'KateMobileAndroid/56 lite-460 (Android 4.4.2; SDK 19; x86; unknown Android SDK built for x86; en)',
            'X-Kate-MobileClient': '1'
        })
        
        vk = vk_session.get_api()
        
        # Проверяем доступ
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

def auth_handler():
    """Обработчик двухфакторной аутентификации"""
    # Код двухфакторной аутентификации будет получен через SMS
    key = input("Введите код подтверждения из SMS: ")
    # Если вы хотите автоматически сохранять данные аутентификации, верните True
    remember_device = True
    return key, remember_device

# Глобальная переменная для VK API
vk = init_vk()

# Обработчик сигналов для корректного завершения
def signal_handler(signum, frame):
    logger.info("Получен сигнал завершения, останавливаем бота...")
    raise SystemExit(0)

signal.signal(signal.SIGINT, signal_handler)

async def search_track(query, expected_title=None, expected_artist=None):
    try:
        logger.info(f"Поиск трека: {query}")
        
        if not vk:
            logger.error("VK API не инициализирован")
            return []
        
        # Используем метод поиска аудио
        search_results = await asyncio.to_thread(vk.audio.search, q=query, count=10, sort=2, v='5.199')
        
        logger.info(f"Результаты поиска: {search_results}")
        
        results = []
        if search_results and 'items' in search_results:
            tasks = []  # Список задач для параллельного выполнения
            for item in search_results['items']:
                tasks.append(process_item(item, expected_title, expected_artist))
            
            results = await asyncio.gather(*tasks)  # Параллельное выполнение задач
            results = [result for result in results if result]  # Фильтруем None
            
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

async def get_m3u8_url(url):
    try:
        headers = {
            'User-Agent': 'VKAndroidApp/7.7-10445 (Android 11; SDK 30; arm64-v8a; Xiaomi M2004J19C; ru; 2340x1080)',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }
        
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    # Ищем URL в m3u8 плейлисте
                    for line in content.split('\n'):
                        if line.startswith('http') and '.mp3' in line:
                            return line.strip()
                return None
    except Exception as e:
        logger.error(f"Ошибка при получении m3u8: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Я бот. Как я могу помочь?')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Вот список доступных команд:\n/start - Начать работу\n/help - Показать справку')

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text)

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
                    # Формируем поисковый запрос для VK
                    search_query = f"{result.get('artist_names', '')} {result.get('title', '')}"
                    
                    # Ищем трек в VK
                    vk_tracks = await search_track(search_query)
                    if vk_tracks:
                        # Берем первый найденный трек
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

# Определение функции для отображения основной клавиатуры
def show_main_keyboard():
    keyboard = [
        ["Поиск по названию"],
        ["Поиск по тексту"],
        ["Избранное"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def search_tracks(query):
    # Разделяем запрос на части, если необходимо
    query_parts = query.split(',')
    tasks = [search_track(part.strip()) for part in query_parts]
    results = await asyncio.gather(*tasks)
    return [track for result in results for track in result]  # Объединяем результаты

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global favorites  # Используем глобальную переменную favorites
    try:
        query = update.message.text.strip()
        logger.info(f"Получен текстовый запрос: {query}")
        
        # Получаем тип поиска из контекста
        search_type = context.user_data.get('search_type', None)
        logger.info(f"Текущий тип поиска: {search_type}")

        # Если пользователь вводит новую команду, сбрасываем тип поиска
        if query.lower() in ["поиск по названию", "поиск по тексту", "избранное"]:
            logger.info("Сбрасываем тип поиска")
            context.user_data['search_type'] = None  # Сбрасываем тип поиска

        # Если тип поиска не установлен, обрабатываем команды выбора
        if search_type is None:
            logger.info("Тип поиска не установлен, обрабатываем команды выбора")
            if query.lower() == "поиск по названию":
                context.user_data['search_type'] = 'title'
                await update.message.reply_text("🔍 Поиск по названию. Введите название песни и (опционально) исполнителя через запятую.", reply_markup=show_main_keyboard())
                logger.info("Установлен тип поиска: 'title'")
                return
            
            if query.lower() == "поиск по тексту":
                context.user_data['search_type'] = 'lyrics'
                await update.message.reply_text("Готов искать по тексту. Введите текст песни.", reply_markup=show_main_keyboard())
                logger.info("Установлен тип поиска: 'lyrics'")
                return
            
            if query.lower() == "избранное":
                await show_favorites(update, context)
                return
            
            if query.lower().startswith("добавить в избранное"):
                # Извлекаем название и URL трека из сообщения
                parts = query[len("добавить в избранное"):].strip().split(',')
                if len(parts) == 2:
                    track_title = parts[0].strip()
                    track_url = parts[1].strip()
                    context.user_data['track_title'] = track_title
                    context.user_data['track_url'] = track_url
                    await add_to_favorites(update, context)
                else:
                    await update.message.reply_text("Пожалуйста, укажите название трека и URL через запятую.")
                return
            
            if query.lower().startswith("удалить из избранного"):
                track_title = query[len("удалить из избранного"):].strip()
                context.user_data['track_title'] = track_title
                await remove_from_favorites(update, context)
                return
            
            await update.message.reply_text("😔 Произошла ошибка при поиске треков.", reply_markup=show_main_keyboard())
            logger.warning("Неизвестная команда введена")
            return

        # Обработка поиска по названию
        if search_type == 'title':
            logger.info(f"Поиск треков по названию: {query}")
            try:
                tracks = await search_tracks(query)  # Используем асинхронный поиск
                if tracks:
                    context.user_data['tracks'] = tracks  # Сохраняем найденные треки в контексте
                    await show_tracks(update, context, tracks)
                else:
                    await update.message.reply_text("😔 Не удалось найти трек. Попробуйте другой.", reply_markup=show_main_keyboard())
                    logger.warning("Не удалось найти трек по запросу")
                
                # Сбрасываем тип поиска после завершения обработки
                context.user_data['search_type'] = None
                return
            
            except Exception as e:
                logger.error(f"Ошибка при поиске треков: {e}")
                await update.message.reply_text("😔 Произошла ошибка при поиске треков.", reply_markup=show_main_keyboard())
                return

        # Обработка поиска по тексту
        if search_type == 'lyrics':
            logger.info(f"Поиск текста песен: {query}")
            try:
                lyrics_results = await search_lyrics(query)  # Асинхронный поиск текста
                if lyrics_results:
                    logger.info(f"Найдено {len(lyrics_results)} результатов на Genius.")
                    # Создаем клавиатуру с найденными треками
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
    
    # Возвращаем клавиатуру после обработки текста
    logger.info("Возвращаем клавиатуру с кнопками")
    await show_main_keyboard(update, context)  # Вызов функции для отображения клавиатуры

# Функция для загрузки избранного
def load_favorites():
    """Загружает избранные треки из файла favorites.json."""
    try:
        if Path('favorites.json').exists():
            with open('favorites.json', 'r', encoding='utf-8') as f:
                logger.info("Загрузка избранного из файла.")
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке избранного: {e}")
        return {}

# Функция для сохранения избранного
def save_favorites(favorites):
    """Сохраняет избранные треки в файл favorites.json."""
    try:
        with open('favorites.json', 'w', encoding='utf-8') as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
        logger.info("Избранное успешно сохранено.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении избранного: {e}")

# Загружаем избранное при старте
favorites = load_favorites()  # Убедитесь, что эта строка находится в правильном месте

# Удалите или закомментируйте этот блок
# async def test_search_lyrics():
#     results = await search_lyrics("ваш текст для поиска")
#     print(results)

# async def main():
#     await test_search_lyrics()

# asyncio.run(main())  # Удалите или закомментируйте эту строку 

# Функция для добавления трека в избранное
async def add_to_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    favorites = load_favorites()

    # Получаем информацию о треке из контекста
    track_title = context.user_data.get('track_title')  # Название трека
    track_url = context.user_data.get('track_url')      # URL трека

    if user_id not in favorites:
        favorites[user_id] = []

    # Проверяем, есть ли трек уже в избранном
    if any(track['title'] == track_title for track in favorites[user_id]):
        await update.message.reply_text("Этот трек уже в избранном.")
        return

    # Добавляем трек в избранное
    favorites[user_id].append({
        "title": track_title,
        "url": track_url,
        "duration": 0  # Укажите длительность, если она известна
    })

    save_favorites(favorites)
    logger.info(f"Добавление трека '{track_title}' в избранное для пользователя {user_id}.")
    await update.message.reply_text(f"Трек '{track_title}' добавлен в избранное!")

# Функция для удаления трека из избранного
async def remove_from_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    favorites = load_favorites()

    # Получаем информацию о треке (например, из сообщения)
    track_title = context.user_data.get('track_title')  # Название трека

    if user_id in favorites:
        # Ищем трек в избранном
        for track in favorites[user_id]:
            if track['title'] == track_title:
                favorites[user_id].remove(track)  # Удаляем трек из избранного
                save_favorites(favorites)
                await update.message.reply_text(f"Трек '{track_title}' удален из избранного.")
                return

    await update.message.reply_text(f"Трек '{track_title}' не найден в избранном.")

# Функция для показа избранного
async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    favorites = load_favorites()
    
    if user_id not in favorites or not favorites[user_id]:
        await update.message.reply_text("У вас пока нет избранных треков.")
        return
    
    # Создаем клавиатуру с избранными треками
    keyboard = []
    for i, track in enumerate(favorites[user_id]):
        keyboard.append([
            InlineKeyboardButton(track['title'], callback_data=f"download_{i}"),  # Кнопка для скачивания
            InlineKeyboardButton("❌", callback_data=f"remove_{i}")  # Кнопка для удаления
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Выберите трек для скачивания или удаления:",
        reply_markup=reply_markup
    )

# Обработчик нажатий на кнопки
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"Получен запрос на кнопку: {query.data}")
    
    user_id = str(update.effective_user.id)

    if query.data.startswith("play_") or query.data.startswith("download_"):
        track_index = int(query.data.split("_")[1])
        favorites = load_favorites()
        
        # Определяем источник трека
        if query.data.startswith("play_"):
            # Для результатов поиска
            tracks = context.user_data.get('tracks', [])
            if not tracks or track_index >= len(tracks):
                await query.answer("Трек не найден.")
                return
            track = tracks[track_index]
        else:
            # Для избранного (download_)
            if user_id not in favorites or track_index >= len(favorites[user_id]):
                await query.answer("Трек не найден в избранном.")
                return
            track = favorites[user_id][track_index]
            
        content = await download_audio(track)
        if content:
            await query.message.reply_audio(audio=content, title=track['title'])
        else:
            await query.message.reply_text("😔 Не удалось скачать трек.")
    
    elif query.data.startswith("add_favorite_"):
        track_index = int(query.data.split("_")[2])
        tracks = context.user_data.get('tracks', [])
        
        if track_index < len(tracks):
            track = tracks[track_index]
            
            # Добавляем трек в избранное
            favorites = load_favorites()
            if user_id not in favorites:
                favorites[user_id] = []
            
            # Проверяем, есть ли трек уже в избранном
            if not any(t['title'] == track['title'] for t in favorites[user_id]):
                favorites[user_id].append(track)
                save_favorites(favorites)
                await query.message.reply_text(f"✅ Трек '{track['title']}' добавлен в избранное!")
            else:
                await query.message.reply_text("Этот трек уже в избранном.")
        else:
            await query.answer("Трек не найден.")
            
    elif query.data.startswith("remove_"):  # Изменено с favorite_ на remove_
        track_index = int(query.data.split("_")[1])
        favorites = load_favorites()
        
        if user_id in favorites and track_index < len(favorites[user_id]):
            # Получаем название трека перед удалением
            track_title = favorites[user_id][track_index]['title']
            # Удаляем трек
            favorites[user_id].pop(track_index)
            save_favorites(favorites)
            
            if favorites[user_id]:
                # Обновляем сообщение с избранным
                keyboard = []
                for i, track in enumerate(favorites[user_id]):
                    keyboard.append([
                        InlineKeyboardButton(track['title'], callback_data=f"download_{i}"),
                        InlineKeyboardButton("❌", callback_data=f"remove_{i}")  # Используем remove_ вместо favorite_
                    ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text(
                    "⭐️ Ваши избранные треки:\nНажмите на название для воспроизведения или ❌ для удаления из избранного",
                    reply_markup=reply_markup
                )
            else:
                await query.message.edit_text("У вас пока нет избранных треков")
            
            # Отправляем сообщение об успешном удалении
            await query.message.reply_text(f"❌ Трек '{track_title}' удален из избранного")
        else:
            await query.answer("Трек не найден")

# Добавляем новую команду для просмотра избранного
async def favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = str(update.effective_user.id)
        favorites = load_favorites()
        
        if user_id not in favorites or not favorites[user_id]:
            await update.message.reply_text("У вас пока нет избранных треков")
            return
            
        # Создаем клавиатуру с избранными треками
        keyboard = []
        tracks = favorites[user_id]
        
        for i, track in enumerate(tracks):
            keyboard.append([
                InlineKeyboardButton(track['title'], callback_data=f"download_{i}"),  # Кнопка для воспроизведения
                InlineKeyboardButton("❌", callback_data=f"remove_{i}")  # Кнопка удаления только в избранном
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⭐️ Ваши избранные треки:\nНажмите на название для воспроизведения или ❌ для удаления из избранного",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе избранного: {e}")
        await update.message.reply_text("😔 Произошла ошибка при загрузке избранного")

# Удалите или закомментируйте этот блок
# async def test_search_lyrics():
#     results = await search_lyrics("ваш текст для поиска")
#     print(results)

# async def main():
#     await test_search_lyrics()

# asyncio.run(main())  # Удалите или закомментируйте эту строку 

# async def main():
#     await test_search_lyrics()

# asyncio.run(main())  # Удалите или закомментируйте эту строку 

async def handle_add_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Предположим, что вы получаете название и URL трека из сообщения
    if len(context.args) < 2:
        await update.message.reply_text("Пожалуйста, укажите название и URL трека.")
        return

    track_title = context.args[0]
    track_url = context.args[1]

    # Сохраняем информацию о треке в контексте
    context.user_data['track_title'] = track_title
    context.user_data['track_url'] = track_url

    # Вызываем функцию добавления в избранное
    await add_to_favorites(update, context) 

async def show_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE, tracks):
    context.user_data['tracks'] = tracks  # Сохраняем найденные треки в контексте
    keyboard = []
    for i, track in enumerate(tracks):
        keyboard.append([
            InlineKeyboardButton(track['title'], callback_data=f"play_{i}"),  # Кнопка для воспроизведения
            InlineKeyboardButton("⭐ Добавить в избранное", callback_data=f"add_favorite_{i}")  # Только кнопка добавления в избранное
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите трек:", reply_markup=reply_markup)

def main():
    application.run_polling() 