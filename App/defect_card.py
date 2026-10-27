"""
Генерация «Дефектной карточки» (xlsx) для записей с отмеченными дефектами.
Пока карточка формируется пустой.
Вызывается только на сервере, при сохранении записи (push с телефона и сохранение
через веб-форму), а не по требованию пользователя.
"""

import io
from django.core.files.base import ContentFile
from openpyxl import Workbook
from .pole_field_schema import has_any_defects


def maybe_attach_defect_card(record) -> None:
    data = record.data if isinstance(record.data, dict) else {}
    if not has_any_defects(data):
        return

    if record.defect_card:
        record.defect_card.delete(save=False)

    workbook = Workbook()
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    record.defect_card.save(f"{record.uuid}.xlsx", ContentFile(buffer.read()), save=True)
