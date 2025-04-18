# Добавить проверку токена при старте
def validate_genius_token():
    try:
        genius = lyricsgenius.Genius(AcmYm1QBtuWfvJwyhoF5DmzKNKFiuI_u-zVJl2sxG0TnkhpeFffwIQPSdwM4Z4yk)
        genius.search_songs("test")
        return True
    except:
        logger.error("Невалидный токен Genius API")
        return False 