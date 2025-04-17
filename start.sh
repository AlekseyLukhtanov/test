#!/bin/bash

# Убедитесь, что используете python3
python3 -m venv venv  # Создаём виртуальное окружение
source venv/bin/activate  # Активируем виртуальное окружение

# Устанавливаем зависимости
pip install -r requirements.txt

# Запускаем основной скрипт
python3 main.py
