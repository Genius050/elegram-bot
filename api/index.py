import json
import logging
from telegram import Update
from .bot import application

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def handler(request):
    try:
        # Проверяем метод запроса
        if request.method == 'GET':
            return {
                'statusCode': 200,
                'body': 'Telegram Bot is running!'
            }
        
        # Для POST запросов (вебхуки от Telegram)
        if request.method == 'POST':
            # Получение тела запроса
            body = await request.body()
            data = json.loads(body)
            
            # Создание объекта Update из данных запроса
            update = Update.de_json(data, application.bot)
            
            # Обработка обновления
            await application.process_update(update)
            
            return {
                'statusCode': 200,
                'body': json.dumps({'status': 'ok'})
            }
            
        return {
            'statusCode': 405,
            'body': 'Method Not Allowed'
        }
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        } 