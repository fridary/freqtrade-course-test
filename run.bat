@echo off
if not exist .env (
    echo Ошибка: файл .env не найден
    echo Скопируй .env.example в .env и укажи путь к данным
    exit /b 1
)
docker compose run --rm freqtrade %*