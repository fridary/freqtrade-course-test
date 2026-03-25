#!/bin/bash
set -e

# Проверяем что .env существует
if [ ! -f .env ]; then
    echo "Ошибка: файл .env не найден"
    echo "Скопируй .env.example в .env и укажи путь к данным"
    exit 1
fi

docker compose run --rm freqtrade "$@"