"""
Сохранение загруженных фото.

Файлы не привязаны к отдельной модели/миграции — просто лежат в MEDIA и на них
возвращается абсолютная ссылка, которая хранится как обычный текст внутри
Record.data.
"""

import uuid
from django.conf import settings
from django.core.files.storage import default_storage
from .record_paths import record_folder


def save_record_photo(uploaded_file, data: dict, request) -> str:
    ext = uploaded_file.name.rsplit(".", 1)[-1] if "." in uploaded_file.name else "jpg"
    folder = record_folder(data)
    path = default_storage.save(f"records/{folder}/{uuid.uuid4()}.{ext}", uploaded_file)
    return request.build_absolute_uri(default_storage.url(path))

def _storage_path_from_url(url: str):
    marker = settings.MEDIA_URL
    idx = url.find(marker)
    return url[idx + len(marker):] if idx != -1 else None

def delete_if_managed(url: str) -> None:
    """Удаляет файл, только если ссылка указывает на наш собственный загруженный
    файл (папка records/...) — а не на что-то введённое вручную."""
    path = _storage_path_from_url(url)
    if path and path.startswith("records/"):
        default_storage.delete(path)

def replace_managed_photo(old_value: str, new_value: str) -> None:
    """Вызывать при замене значения поля с фото: если старое значение реально
    менялось и было файлом — старый файл удаляется."""
    if old_value and old_value != new_value:
        delete_if_managed(old_value)
