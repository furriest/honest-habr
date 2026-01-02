import logging
import json
import os
from dotenv import load_dotenv
import feedparser
import requests
from groq import Groq
from telegram import Bot
from telegram.constants import ParseMode  # <-- Вот правильный импорт
import asyncio
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загрузка .env
load_dotenv()

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
RSS_OUTPUT_FILE = os.getenv('RSS_OUTPUT_FILE', 'rss.xml')

ARTICLES_FILE = 'articles.json'

def clean_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for img in soup.find_all('img'):
        img.decompose()
    return soup.get_text(separator=' ', strip=True)

def clean_description_for_telegram(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for img in soup.find_all('img'):
        img.decompose()
    for tag in soup.find_all(['div', 'span']):
        tag.unwrap()
    for p in soup.find_all('p'):
        p.replace_with('\n\n' + p.get_text(strip=True))
    for br in soup.find_all('br'):
        br.replace_with('\n')
    for strong in soup.find_all('strong'):
        strong.name = 'b'
    for em in soup.find_all('em'):
        em.name = 'i'
    return str(soup)

def get_first_image_url(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    img = soup.find('img')
    if img and 'src' in img.attrs:
        return img['src']
    return None

async def send_to_telegram(bot: Bot, channel_id: str, new_title: str, description: str, article_url: str):
    try:
        img_url = get_first_image_url(description)
        
        # Кликабельный заголовок
        linked_title = f'<b><a href="{article_url}">{new_title}</a></b>'
        
        # Очищаем описание и разбиваем на абзацы
        clean_desc = clean_description_for_telegram(description)
        paragraphs = [p.strip() for p in clean_desc.split('\n\n') if p.strip()]
        
        # Начинаем формировать подпись: заголовок + абзацы по одному, пока влезаем
        caption_parts = [linked_title]
        current_length = len(linked_title) + 2  # +2 за переносы
        
        max_caption_length = 950  # безопасный лимит
        
        for para in paragraphs:
            # Добавляем абзац с двумя переносами
            test_length = current_length + len(para) + 2
            if test_length > max_caption_length:
                break
            caption_parts.append(para)
            current_length = test_length
        
        # Если обрезали — добавляем "Читать дальше" как ссылку
        if len(caption_parts) < len(paragraphs) + 1:  # +1 потому что заголовок уже есть
            caption_parts.append(f'\n\n<tg-spoiler>… <a href="{article_url}">Читать дальше на Habr</a></tg-spoiler>')
        
        caption = '\n\n'.join(caption_parts)
        
        # Отправляем фото с подписью (или просто текст, если нет фото)
        if img_url:
            await bot.send_photo(
                chat_id=channel_id,
                photo=img_url,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        else:
            # Если нет фото — можно чуть больше текста, но всё равно обрезаем красиво
            if len(caption) > 4000:
                caption = caption[:4000] + f'\n\n<tg-spoiler>… <a href="{article_url}">Читать дальше</a></tg-spoiler>'
            await bot.send_message(
                chat_id=channel_id,
                text=caption,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        
        logger.info("Успешно отправлено в Telegram (компактная версия)")
    
    except Exception as e:
        logger.error(f"Ошибка отправки в Telegram: {e}")
                        
async def main_async():
    logger.info("Запуск сервиса...")

    if not all([GROQ_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID]):
        logger.error("Отсутствуют обязательные переменные окружения.")
        return

    # Загрузка RSS
    rss_url = 'https://habr.com/ru/rss/articles/?fl=ru'
    try:
        response = requests.get(rss_url)
        response.raise_for_status()
        rss_content = response.text
        feed = feedparser.parse(rss_content)
    except Exception as e:
        logger.error(f"Не удалось загрузить RSS: {e}")
        return

    # Загрузка базы обработанных статей
    articles = {}
    if os.path.exists(os.path.join('/app/data',ARTICLES_FILE)):
        try:
            with open(os.path.join('/app/data',ARTICLES_FILE), 'r', encoding='utf-8') as f:
                articles = json.load(f)
            logger.info(f"Загружено {len(articles)} ранее обработанных статей.")
        except Exception as e:
            logger.error(f"Ошибка чтения articles.json: {e}")

    # Подготовка клиентов
    groq_client = Groq(api_key=GROQ_API_KEY)
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Загрузка промпта
    try:
        with open(os.path.join('/app/data','prompt.txt'), 'r', encoding='utf-8') as f:
            prompt_template = f.read()
    except Exception as e:
        logger.error(f"Не удалось загрузить prompt.txt: {e}")
        return

    new_articles = {}

    for entry in feed.entries:
        guid = entry.get('guid')
        if not guid or guid in articles:
            continue

        old_title = entry.get('title', '')
        description = entry.get('description', '')

        clean_title = clean_text(old_title)
        clean_desc = clean_text(description)

        prompt = prompt_template.replace('{{TITLE}}', clean_title).replace('{{DESCRIPTION}}', clean_desc)

        try:
            completion = groq_client.chat.completions.create(
                model="meta-llama/llama-4-maverick-17b-128e-instruct",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.95,
                max_tokens=128
            )
            new_title = completion.choices[0].message.content.strip()
            logger.info(f"Новый заголовок для {guid}: {new_title}")
        except Exception as e:
            logger.error(f"Ошибка Groq API для {guid}: {e}")
            continue

        new_articles[guid] = {
            'guid': guid,
            'old_title': old_title,
            'new_title': new_title
        }

        # Асинхронная отправка в Telegram
        await send_to_telegram(bot, TELEGRAM_CHANNEL_ID, new_title, description, guid)

    # Сохранение новых статей
    if new_articles:
        articles.update(new_articles)
        try:
            with open(os.path.join('/app/data/',ARTICLES_FILE), 'w', encoding='utf-8') as f:
                json.dump(articles, f, ensure_ascii=False, indent=4)
            logger.info(f"Сохранено {len(new_articles)} новых статей в {ARTICLES_FILE}")
        except Exception as e:
            logger.error(f"Ошибка сохранения articles.json: {e}")

        # Генерация модифицированной RSS-ленты
        try:
            root = ET.fromstring(rss_content.encode('utf-8'))

            # Определяем namespace (если есть)
            ns = None
            if '}' in root.tag:
                ns_uri = root.tag.split('}')[0][1:]
                ns = {'ns': ns_uri}
                channel_path = './/ns:channel'
                item_path = './/ns:item'
                title_path = 'ns:title'
                desc_path = 'ns:description'
                guid_path = 'ns:guid'
                managing_editor_path = 'ns:managingEditor'
            else:
                channel_path = './/channel'
                item_path = './/item'
                title_path = 'title'
                desc_path = 'description'
                guid_path = 'guid'
                managing_editor_path = 'managingEditor'

            # Находим канал
            channel = root.find(channel_path, ns)
            if channel is None:
                raise ValueError("Не найден элемент <channel> в RSS")

            # Удаляем managingEditor, если есть
            managing_editor = channel.find(managing_editor_path, ns)
            if managing_editor is not None:
                channel.remove(managing_editor)

            # Заменяем title и description канала
            channel_title = channel.find(title_path, ns)
            if channel_title is not None:
                channel_title.text = "Честная ИИ-лента Хабра"

            channel_desc = channel.find(desc_path, ns)
            if channel_desc is not None:
                channel_desc.text = "Честная ИИ-лента Хабра"

            # Заменяем заголовки в статьях
            for item in root.findall(item_path, ns):
                guid_elem = item.find(guid_path, ns)
                if guid_elem is not None and guid_elem.text and guid_elem.text.strip() in articles:
                    guid = guid_elem.text.strip()
                    title_elem = item.find(title_path, ns)
                    if title_elem is not None:
                        title_elem.text = articles[guid]['new_title']

            # Красивая и компактная запись без лишних пробелов и пустых строк
            def indent(elem, level=0):
                """Компактный indent без пустых строк"""
                i = "\n" + level * "  "
                if len(elem):
                    if not elem.text or not elem.text.strip():
                        elem.text = i + "  "
                    for e in elem:
                        indent(e, level + 1)
                        if not e.tail or not e.tail.strip():
                            e.tail = i + "  "
                    if not elem[-1].tail or not elem[-1].tail.strip():
                        elem[-1].tail = i
                else:
                    if level and (not elem.tail or not elem.tail.strip()):
                        elem.tail = i

            indent(root)

            # Записываем файл чисто и компактно
            tree = ET.ElementTree(root)
            with open(os.path.join('/app/data',RSS_OUTPUT_FILE), 'wb') as f:
                tree.write(
                    f,
                    encoding='utf-8',
                    xml_declaration=True,
                    method='xml'
                )

            # Убираем лишние пустые строки в конце файла (на всякий случай)
            with open(os.path.join('/app/data',RSS_OUTPUT_FILE), 'r', encoding='utf-8') as f:
                lines = f.readlines()
            with open(os.path.join('/app/data',RSS_OUTPUT_FILE), 'w', encoding='utf-8', newline='\n') as f:
                for line in lines:
                    if line.strip() or (f.tell() > 0 and f.buffer and f.buffer[-1] != b'\n'):
                        f.write(line.rstrip('\n') + '\n')

            logger.info(f"Сгенерирована чистая модифицированная лента: {RSS_OUTPUT_FILE}")

        except Exception as e:
            logger.error(f"Ошибка генерации RSS: {e}")
        
    logger.info("Сервис завершён.")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()