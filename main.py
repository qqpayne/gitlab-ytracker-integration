import re
import requests
from fastapi import FastAPI, Request, Header, HTTPException
import logging

# Настройки тегов
TAG_OPENED = "mr-opened"
TAG_MERGED = "mr-merged"

# Регулярное выражение для поиска ключей Трекера (например, TEST-123, MYPROJ-45)
ISSUE_KEY_REGEX = re.compile(r"[A-Z][A-Z0-9]+-\d+")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def add_tag_to_tracker(
    issue_key: str, tag: str, tracker_org_id: str, tracker_token: str
):
    """Отправляет запрос в API Яндекс Трекера для добавления тега"""
    url = f"https://api.tracker.yandex.net/v3/issues/{issue_key}"
    headers = {
        "Authorization": f"OAuth {tracker_token}",
        "X-Org-ID": tracker_org_id,
        "Content-Type": "application/json",
    }
    # Специальный синтаксис Трекера для добавления в массив без перезаписи
    payload = {"tags": {"add": [tag]}}

    try:
        response = requests.patch(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"Тег '{tag}' успешно добавлен к задаче {issue_key}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при добавлении тега к {issue_key}: {e}")
        if response is not None:
            logger.error(f"Ответ Трекера: {response.text}")


@app.post("/webhook")
async def gitlab_webhook(
    request: Request, x_org_id: str, x_gitlab_token: str = Header()
):
    if x_gitlab_token is None or len(x_gitlab_token) == 0:
        logger.warning("Попытка доступа с неверным X-Gitlab-Token")
        raise HTTPException(status_code=401, detail="Invalid token")

    body = await request.json()

    # 2. Убеждаемся, что это событие Merge Request
    if body.get("object_kind") != "merge_request":
        return {"status": "ignored", "reason": "Not a merge request event"}

    mr_attrs = body.get("object_attributes", {})
    action = mr_attrs.get("action")

    # 3. Определяем нужный тег в зависимости от действия
    tag_to_add = None
    if action == "open":
        tag_to_add = TAG_OPENED
    elif action == "merge":
        tag_to_add = TAG_MERGED
    else:
        return {"status": "ignored", "reason": f"Action '{action}' is ignored"}

    # 4. Ищем ключи Трекера в названии, описании и ветке
    text_to_search = f"{mr_attrs.get('title', '')} {mr_attrs.get('description', '')} {mr_attrs.get('source_branch', '')}"

    # Ищем все совпадения и убираем дубликаты (set)
    issue_keys = set(ISSUE_KEY_REGEX.findall(text_to_search))
    if not issue_keys:
        logger.info(f"Ключи Трекера не найдены в MR {mr_attrs.get('title', '')}")
        return {"status": "success", "message": "No tracker keys found"}

    # 5. Добавляем теги ко всем найденным задачам
    for issue_key in issue_keys:
        add_tag_to_tracker(issue_key, tag_to_add, x_org_id, x_gitlab_token)

    return {
        "status": "success",
        "processed_issues": list(issue_keys),
        "tag": tag_to_add,
    }
