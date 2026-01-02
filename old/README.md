<img width="614" height="780" alt="image" src="https://github.com/user-attachments/assets/b0d60dd7-a72b-4db4-af93-f07dcd772e44" />


# Честная лента | Habr

Для запуска рекомндуем облако Amvera Cloud - конфигурационный файл, необходимый для развертывания (`amvera.yml`) сохранен в репозитории. Для запуска вам понадобится лишь загрузить все файлы в Code (+prompt.txt в Data), добавить перечисленные ниже переменные окружения через интерфейс и добавить внешний домен.

> https://habr.com/ru/companies/amvera/articles/981136/

## Переменные окружения | Environment variables

**Обязательные**
Без них проект не запустится или не будет работать корректно:
- `DATA_DIR`: для Amvera **ОБЯЗАТЕЛЬНО** значение `/data`;
- `AMVERA_API_TOKEN`: ваш токен от Amvera LLM Inference API. Получается в ЛК Amvera.
- `PROMPT_PATH`: для Amvera **ОБЯЗАТЕЛЬНО** значение `/data/prompt.txt`

**Опциональные**
Проект может запуститься без них. Через двоеточие указано значение по умолчанию:
- `RSS_URL`: `https://habr.com/ru/rss/articles/?fl=ru`
- `AMVERA_ENDPOINT`: `https://kong-proxy.yc.amvera.ru/api/v1/models/deepseek`
- `REFRESH_SECONDS`: `30`
- `AI_WORKERS`: `4` - Сколько запросов одновременно может уйти к Amvera LLM Inference API. Чем больше значение, тем быстрее обработаются все заголовки. Рекомендуемое значение <=10.
- `LOCK_STALE_SECONDS`: `900`
- `MAX_STORE`: `150` - Сколько максмимум статей будет храниться в `articles.json`. Чем больше значение, тем больше обработанных заголовков и страниц.  

---

<img width="1686" height="499" alt="image" src="https://github.com/user-attachments/assets/8cd244c4-3cfb-4820-b8ef-517cc9fbcec7" />
