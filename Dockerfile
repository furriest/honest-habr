# Используем базовый образ Python 3.11 slim
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Создаём подпапку для данных (article.json и rss.xml)
RUN mkdir -p /app/data

# Копируем файлы скрипта и .env
COPY honest-habr.py .
COPY requirements.txt .
COPY .env .

# Устанавливаем необходимые зависимости для работы cron
RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Создаем cron-файл для запуска скрипта каждую полночь
# Указываем cd в /app для правильной рабочей директории
RUN echo "0 0 * * * cd /app && python honest-habr.py >> /var/log/cron.log 2>&1" > /etc/cron.d/my-cron-job

# Даем права на выполнение cron-файла
RUN chmod 0644 /etc/cron.d/my-cron-job

# Применяем cron job
RUN crontab /etc/cron.d/my-cron-job

# Создаем файл лога и даем права на запись
RUN touch /var/log/cron.log && chmod 666 /var/log/cron.log

# Запускаем cron на переднем плане (не нужно tail)
CMD ["cron", "-f"]