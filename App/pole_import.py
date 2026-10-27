import datetime
import re
import uuid

from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from .models import Record
from .defect_card import maybe_attach_defect_card


class PoleImportError(Exception):
    pass


_REF_RE = re.compile(r"^([A-Z]+)(\d*)$")


def parse_ref(ref: str) -> dict:
    """Разбирает ссылку на столбец/ячейку/диапазон, введённую для поля.

    'C' -> только столбец. 'C:E' -> столбцы C-E, без строк. 'C9' -> столбец C,
    только строка 9. 'C9:E28' -> столбцы C-E и строки 9-28 — если строка указана
    С ОБЕИХ сторон диапазона, она задаёт границы чтения именно для этого поля;
    если только с одной стороны или вообще не указана — границы строк не заданы
    (используются общие для листа, см. _import_from_sheet). Возвращает
    {"columns": [...], "start_row": int|None, "end_row": int|None}."""
    ref = (ref or "").strip().upper().replace(" ", "")
    empty = {"columns": [], "start_row": None, "end_row": None}
    if not ref:
        return empty
    try:
        parts = ref.split(":") if ":" in ref else [ref]
        parsed = []
        for part in parts:
            match = _REF_RE.match(part)
            if not match:
                return empty
            col, row = match.group(1), match.group(2)
            parsed.append((col, int(row) if row else None))

        if len(parsed) == 2:
            (col1, row1), (col2, row2) = parsed
            start_idx = column_index_from_string(col1)
            end_idx = column_index_from_string(col2)
            if start_idx > end_idx:
                start_idx, end_idx = end_idx, start_idx
            columns = [get_column_letter(i) for i in range(start_idx, end_idx + 1)]
            if row1 is not None and row2 is not None:
                return {"columns": columns, "start_row": min(row1, row2), "end_row": max(row1, row2)}
            return {"columns": columns, "start_row": None, "end_row": None}

        col, row = parsed[0]
        return {"columns": [col], "start_row": row, "end_row": row}
    except Exception:
        return empty


def cell_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%d.%m.%Y")
    return str(value).strip()


def _resolve_sheet(workbook, sheet_ref: str):
    """Пустая ссылка -> активный лист. Только цифры -> номер листа по порядку (с 1).
    Иначе -> точное имя листа."""
    sheet_ref = (sheet_ref or "").strip()
    if not sheet_ref:
        return workbook.active
    if sheet_ref.isdigit():
        index = int(sheet_ref) - 1
        if 0 <= index < len(workbook.worksheets):
            return workbook.worksheets[index]
        raise PoleImportError(
            f"Лист №{sheet_ref} не найден — в файле листов: {len(workbook.worksheets)}"
        )
    if sheet_ref in workbook.sheetnames:
        return workbook[sheet_ref]
    raise PoleImportError(f"Лист «{sheet_ref}» не найден в файле")


EMPTY_ROW_LIMIT = 10


def dedup_key(data: dict):
    """Естественный ключ физической опоры: место + номер (+ индекс, различающий опоры
    с одинаковым номером вроде "15" и "15а"). Без номера опоры ключ не строим — пустой
    pole_number не может служить признаком дубликата, иначе схлопнутся разные записи."""
    pole_number = str(data.get("pole_number") or "").strip()
    if not pole_number:
        return None
    return (
        str(data.get("directorate") or "").strip(),
        str(data.get("ks_region") or "").strip(),
        str(data.get("station") or "").strip(),
        pole_number,
        str(data.get("pole_index") or "").strip(),
    )


def existing_pole_keys() -> set:
    """Ключи всех уже сохранённых опор — чтобы импорт не плодил дубликаты записей для
    той же самой опоры (например, при повторной загрузке того же файла)."""
    keys = set()
    rows = Record.objects.values_list(
        "data__directorate", "data__ks_region", "data__station", "data__pole_number", "data__pole_index",
    )
    for directorate, ks_region, station, pole_number, pole_index in rows:
        pole_number = str(pole_number or "").strip()
        if not pole_number:
            continue
        keys.add((
            str(directorate or "").strip(), str(ks_region or "").strip(), str(station or "").strip(),
            pole_number, str(pole_index or "").strip(),
        ))
    return keys


def _import_from_sheet(sheet, header_row, mapping: dict, account, seen_keys: set, directorate_override: str = "") -> tuple:
    """mapping: {field_key: {"columns": [...], "start_row": int|None, "end_row": int|None}}.
    Если хотя бы одно поле на листе задаёт строки прямо в своей ссылке — диапазон строк
    для всего листа берётся как объединение (минимальный старт, максимальный конец)
    таких полей, и защита от пустых строк не применяется (раз границы заданы явно —
    доверяем им, даже если внутри есть длинные пустые промежутки). Если ни одно поле
    строк не задаёт — как раньше: header_row+1 и до конца листа, с обрывом после
    длинной серии пустых строк подряд (у Excel max_row часто сильно завышен).
    Возвращает (created, skipped_duplicates). seen_keys копится по всем листам одного
    импорта, поэтому дубликат внутри самого файла тоже будет пойман, а не только
    совпадение с уже существующей в базе записью."""
    fallback_fields = {}
    if "directorate" not in mapping:
        directorate_value = directorate_override or getattr(account, "directorate", "")
        if directorate_value:
            fallback_fields["directorate"] = directorate_value
    for field in ("ks_region", "station"):
        if field not in mapping and getattr(account, field, ""):
            fallback_fields[field] = getattr(account, field)

    explicit_starts = [m["start_row"] for m in mapping.values() if m["start_row"] is not None]
    explicit_ends = [m["end_row"] for m in mapping.values() if m["end_row"] is not None]
    row_range = (
        range(min(explicit_starts), max(explicit_ends) + 1)
        if explicit_starts
        else range(header_row + 1, sheet.max_row + 1)
    )

    to_create = []
    skipped = 0
    empty_streak = 0
    for row in row_range:
        row_data = {}
        has_data = False
        for field_key, field_map in mapping.items():
            pieces = [cell_to_text(sheet[f"{col}{row}"].value) for col in field_map["columns"]]
            pieces = [p for p in pieces if p]
            if pieces:
                row_data[field_key] = ",".join(pieces)
                has_data = True

        if not has_data:
            empty_streak += 1
            if not explicit_starts and empty_streak >= EMPTY_ROW_LIMIT:
                break
            continue
        empty_streak = 0

        for field, value in fallback_fields.items():
            row_data.setdefault(field, value)

        key = dedup_key(row_data)
        if key is not None:
            if key in seen_keys:
                skipped += 1
                continue
            seen_keys.add(key)

        to_create.append(Record(
            uuid=str(uuid.uuid4()),
            data=row_data,
            last_modified=timezone.now(),
            updated_by=account.username,
        ))

    # Тысячи отдельных Record.objects.create() — по одному INSERT на строку — на
    # большом файле не укладывались в таймаут воркера gunicorn. bulk_create сводит
    # это к нескольким запросам вместо тысяч отдельных round-trip'ов к БД.
    Record.objects.bulk_create(to_create, batch_size=500)
    for record in to_create:
        maybe_attach_defect_card(record)

    return len(to_create), skipped


def import_poles(uploaded_file, sheet_configs: list, account) -> tuple:
    """sheet_configs: [{"sheet_ref": str, "header_row": int|None, "mapping": dict,
    "directorate_override": str}, ...] — каждый лист читается по своим настройкам,
    потому что структура таблицы может отличаться даже между листами одного файла.
    Возвращает (created, skipped_duplicates) суммарно по всем листам."""
    try:
        workbook = load_workbook(uploaded_file, data_only=True)
    except Exception:
        raise PoleImportError("Не удалось прочитать файл — убедитесь, что это .xlsx")

    seen_keys = existing_pole_keys()
    created = 0
    skipped = 0
    for config in sheet_configs:
        sheet = _resolve_sheet(workbook, config["sheet_ref"])
        sheet_created, sheet_skipped = _import_from_sheet(
            sheet, config["header_row"], config["mapping"], account, seen_keys,
            config.get("directorate_override", ""),
        )
        created += sheet_created
        skipped += sheet_skipped
    return created, skipped
