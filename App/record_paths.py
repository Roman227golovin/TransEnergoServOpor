"""
Построение пути к папке файлов конкретной опоры: Дирекция/Район КС/Станция/Опора —
та же иерархия, что в веб-интерфейсе (см. views_web.LEVELS).

Без внешних Django-зависимостей используется и из models.py (upload_to),
и из photo_upload.py.
"""

import re

# Дирекция/район/станция — свободный текст, который вводят люди (регистрация,
# запись опоры). Их нельзя подставлять в путь на диске как есть.
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]+')

def safe_segment(value) -> str:
    value = str(value or "").strip()
    value = _UNSAFE_CHARS.sub("_", value)
    value = value.strip(". ") or "нет"
    return value[:100]

def record_folder(data: dict) -> str:
    fields = ("directorate", "ks_region", "station", "pole_number")
    return "/".join(safe_segment(data.get(field)) for field in fields)
