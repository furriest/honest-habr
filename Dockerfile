# Используем базовый образ Python 3.11 slim
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы скрипта и .env
COPY honest-habr.py .
COPY requirements.txt .
COPY .env .

# Устанавливаем необходимые зависимости для работы cron
RUN apt-get update && apt-get install -y cron

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Создаем cron-файл для запуска скрипта каждую полночь
RUN echo "5 0 * * * python /app/honest-habr.py >> /var/log/cron.log 2>&1" > /etc/cron.d/my-cron-job

# Даем права на выполнение cron-файла
RUN chmod 0644 /etc/cron.d/my-cron-job

# Применяем cron job
RUN crontab /etc/cron.d/my-cron-job

# Создаем файл лога
RUN touch /var/log/cron.log

# Запускаем cron в фоновом режиме и держим контейнер активным
CMD cron && tail -f /var/log/cron.log