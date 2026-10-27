import uuid
from functools import wraps
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from passlib.context import CryptContext
from .models import Account, Record, Protocol, OrgFile, InspectionPlan
from . import pole_field_schema
from .defect_card import maybe_attach_defect_card
from .photo_upload import save_record_photo, replace_managed_photo
from . import pole_import

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

LEVELS = ["directorate", "distance", "ks_region", "station"]
LEVEL_LABELS = {
    "directorate": "Дирекция по энергообеспечению",
    "distance": "Дистанция электроснабжения",
    "ks_region": "Район контактной сети",
    "station": "Станция, Перегон",
}

def require_web_login(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        account_uuid = request.session.get("account_uuid")
        if not account_uuid:
            return redirect("web_login")
        account = Account.objects.filter(uuid=account_uuid).first()
        if account is None:
            request.session.flush()
            return redirect("web_login")
        request.web_account = account
        return view_func(request, *args, **kwargs)
    return wrapper

def web_login(request):
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        account = Account.objects.filter(username=username).first()
        if account and pwd_context.verify(password, account.password_hash):
            request.session["account_uuid"] = account.uuid
            return redirect("web_home")
        error = "Неверный логин или пароль"
    return render(request, "web/login.html", {"error": error})

def web_logout(request):
    request.session.flush()
    return redirect("web_login")

@require_web_login
def web_home(request):
    """Главная страница — верхний уровень меню. Пока по-настоящему работает только
    «Информация», остальные пять — заглушки-кнопки под будущие разделы."""
    return render(request, "web/home.html", {"account": request.web_account})

def _pole_number(record):
    raw = record.data.get("pole_number") if isinstance(record.data, dict) else None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None

def _split_odd_even(records):
    """Опоры раскладываются на два столбца по чётности номера — так и на сайте
    удобнее ориентироваться (нечётные/чётные обычно стоят по разным сторонам пути).
    Внутри столбца — по возрастанию номера; записи без номера уходят в конец."""
    odd, even = [], []
    for record in records:
        number = _pole_number(record)
        (even if number is not None and number % 2 == 0 else odd).append(record)

    def sort_key(record):
        number = _pole_number(record)
        return (number is None, number or 0)

    odd.sort(key=sort_key)
    even.sort(key=sort_key)
    return odd, even

def _search_matches(records, query):
    """И для поиска в пределах станции, и для глобального — ищем только по
    номеру/индексу опоры, как в поиске на телефоне (station_records_screen.dart)."""
    q = query.strip().lower()
    if not q:
        return list(records)
    matches = []
    for record in records:
        data = record.data if isinstance(record.data, dict) else {}
        pole = str(data.get("pole_number") or "").lower()
        pole_index = str(data.get("pole_index") or "").lower()
        if q in pole or q in pole_index:
            matches.append(record)
    return matches

def _build_tree(records, levels, path, leaf_url_fn):
    """Строит вложенные группы по levels (произвольный префикс LEVELS — от 1 до 4
    уровней, используется и Книгой опор, и файловыми разделами «Информации»).
    Последний уровень — лист: вместо вложенного списка ведёт по ссылке, которую для
    накопленного пути строит leaf_url_fn."""
    field = levels[0]
    groups = {}
    for record in records:
        value = record.data.get(field) if isinstance(record.data, dict) else None
        value = value if value else "(не указано)"
        groups.setdefault(value, []).append(record)

    remaining_levels = levels[1:]
    nodes = []
    for label in sorted(groups.keys()):
        sub_records = groups[label]
        sub_path = {**path, field: label}
        nodes.append({
            "label": label,
            "count": len(sub_records),
            "url": None if remaining_levels else leaf_url_fn(sub_path),
            "children": _build_tree(sub_records, remaining_levels, sub_path, leaf_url_fn) if remaining_levels else None,
        })
    return nodes

def _station_url(path: dict) -> str:
    return reverse("web_station_records") + "?" + urlencode({
        "directorate": path.get("directorate", ""),
        "ks_region": path.get("ks_region", ""),
        "station": path.get("station", ""),
    })

@require_web_login
def web_pole_book(request):
    """Книга опор — то, что раньше было главной страницей сайта. Для роли ЭЧ (и
    только для неё) дерево и поиск строятся по readable_records()/readable-полям,
    поэтому она видит соседние ЭЧ/ЭЧК своей Дирекции — но это только просмотр,
    редактирование по-прежнему ограничено строгой зоной (см. web_record_detail)."""
    account = request.web_account
    own_scope_fields = Account.ROLE_SCOPE_FIELDS.get(account.role, [])
    readable_fields = account.readable_scope_field_names()
    # readable_fields может не доходить до самого глубокого уровня иерархии, если между
    # уже зафиксированными полями пропущен уровень (у ЭЧ это ks_region без "Дистанции"
    # между directorate и ним) — поэтому берём не разницу множеств, а всё, что идёт в
    # LEVELS ПОСЛЕ самого глубокого уже зафиксированного уровня.
    scoped_positions = [LEVELS.index(f) for f in readable_fields if f in LEVELS]
    remaining_levels = LEVELS[max(scoped_positions, default=-1) + 1:]
    own_path = {f: getattr(account, f) for f in readable_fields}

    if not remaining_levels:
        # Роль (ЭЧК) уже привязана к конкретной станции — смотреть тут больше
        # не на что, сразу ведём на страницу её опор.
        return redirect(_station_url(own_path))

    query = request.GET.get("q", "").strip()
    scope_levels = [(LEVEL_LABELS[f], getattr(account, f)) for f in own_scope_fields]
    sees_neighbors = readable_fields != own_scope_fields

    if query:
        matches = _search_matches(account.readable_records(), query)
        odd, even = _split_odd_even(matches)
        return render(request, "web/records.html", {
            "account": account, "scope_levels": scope_levels, "sees_neighbors": sees_neighbors,
            "query": query, "search_records_odd": odd, "search_records_even": even,
        })

    tree_nodes = _build_tree(list(account.readable_records()), remaining_levels, own_path, _station_url)
    return render(request, "web/records.html", {
        "account": account, "scope_levels": scope_levels, "sees_neighbors": sees_neighbors,
        "query": "", "tree_nodes": tree_nodes,
    })

@require_web_login
def web_station_records(request):
    account = request.web_account
    directorate = request.GET.get("directorate", "")
    ks_region = request.GET.get("ks_region", "")
    station = request.GET.get("station", "")
    query = request.GET.get("q", "").strip()
    km = request.GET.get("km", "").strip()
    pk = request.GET.get("pk", "").strip()
    m = request.GET.get("m", "").strip()

    records = account.readable_records()
    if directorate:
        records = records.filter(data__directorate=directorate)
    if ks_region:
        records = records.filter(data__ks_region=ks_region)
    if station:
        records = records.filter(data__station=station)
    if km:
        records = records.filter(data__km=km)
    if pk:
        records = records.filter(data__pk=pk)
    if m:
        records = records.filter(data__m=m)

    matches = _search_matches(records, query) if query else list(records)
    odd, even = _split_odd_even(matches)

    return render(request, "web/station.html", {
        "station": station or "(не указано)",
        "directorate": directorate,
        "ks_region": ks_region,
        "query": query,
        "km": km,
        "pk": pk,
        "m": m,
        "records_odd": odd,
        "records_even": even,
    })

MAX_IMPORT_SHEETS = 20

@require_web_login
def web_add_pole(request):
    account = request.web_account
    if account.role not in ("TE", "NTE"):
        return render(request, "web/add_pole.html", {"forbidden": True})

    context = {"fields_by_sheet": pole_field_schema.sheets()}

    if request.method == "POST":
        uploaded = request.FILES.get("excel_file")
        count_raw = request.POST.get("sheets_count", "").strip()
        sheet_count = int(count_raw) if count_raw.isdigit() else 0
        sheet_range = range(1, sheet_count + 1)
        context["sheet_range"] = sheet_range

        sheet_configs = []
        form_error = None
        for i in sheet_range:
            sheet_ref = request.POST.get(f"sheet_ref_{i}", "").strip()
            header_row_raw = request.POST.get(f"header_row_{i}", "").strip()
            directorate_override = request.POST.get(f"directorate_override_{i}", "").strip()

            mapping = {}
            for f in pole_field_schema.FIELDS:
                if f.type in ("computed", "file"):
                    continue
                ref_info = pole_import.parse_ref(request.POST.get(f"cell_{i}_{f.key}", ""))
                if ref_info["columns"]:
                    mapping[f.key] = ref_info

            # Блок листа без строки заголовков и без единого столбца — его просто не
            # заполняли, молча пропускаем, а не считаем ошибкой.
            if not header_row_raw and not mapping:
                continue

            if not mapping:
                form_error = f"Лист {i}: укажите столбец хотя бы для одного поля"
                break

            # Строки для чтения можно задать либо тут одним числом на весь лист, либо
            # прямо в ссылках отдельных полей (C9:C28) — тогда это поле необязательно.
            has_explicit_rows = any(m["start_row"] is not None for m in mapping.values())
            header_row_valid = header_row_raw.isdigit() and int(header_row_raw) >= 1

            if not has_explicit_rows and not header_row_valid:
                form_error = (
                    f"Лист {i}: укажите номер строки с заголовками, либо строки прямо "
                    f"в ссылках на ячейки (например, C9:C28)"
                )
                break
            if header_row_raw and not header_row_valid:
                form_error = f"Лист {i}: номер строки с заголовками должен быть целым числом от 1"
                break

            sheet_configs.append({
                "sheet_ref": sheet_ref,
                "header_row": int(header_row_raw) if header_row_valid else None,
                "mapping": mapping,
                "directorate_override": directorate_override,
            })

        if not uploaded:
            context["error"] = "Выберите файл .xlsx"
        elif form_error:
            context["error"] = form_error
        elif not sheet_configs:
            context["error"] = "Настройте хотя бы один лист"
        else:
            try:
                created, skipped = pole_import.import_poles(uploaded, sheet_configs, account)
                context["success"] = True
                context["created"] = created
                context["skipped"] = skipped
            except pole_import.PoleImportError as e:
                context["error"] = str(e)

    else:
        sheets_param = request.GET.get("sheets", "").strip()
        if sheets_param.isdigit() and 1 <= int(sheets_param) <= MAX_IMPORT_SHEETS:
            context["sheet_range"] = range(1, int(sheets_param) + 1)
        else:
            context["choose_count"] = True
            if sheets_param:
                context["error"] = f"Укажите число от 1 до {MAX_IMPORT_SHEETS}"

    return render(request, "web/add_pole.html", context)

@require_web_login
def web_record_detail(request, record_uuid):
    account = request.web_account
    record = account.readable_records().filter(uuid=record_uuid).first()
    if record is None:
        return render(request, "web/record_detail.html", {"not_found": True})

    can_edit_record = account.can_edit_record(record)
    data = dict(record.data) if isinstance(record.data, dict) else {}

    if request.method == "POST":
        if not can_edit_record:
            # Соседняя запись (видна только роли ЭЧ через readable_records) — сюда
            # можно попасть только вручную собранным POST-запросом, честно отказываем.
            return render(request, "web/record_detail.html", {"not_found": True})

        dismantled_before = pole_field_schema.is_dismantled(data)
        changes = []

        # Один проход по порядку схемы: вычисляемые поля идут в списке после своих
        # зависимостей, поэтому к моменту их обработки исходные значения уже свежие.
        for f in pole_field_schema.FIELDS:
            if f.type == "file":
                continue

            if f.type == "computed":
                if f.enabled_when and not f.enabled_when(data):
                    continue
                new_value = f.compute(data) or ""
            else:
                if not pole_field_schema.can_edit_field(account.role, f.key):
                    continue
                if f.enabled_when and not f.enabled_when(data):
                    continue
                if dismantled_before and f.key != "dismantle_date":
                    continue
                if f.key == "safety_tie" and request.FILES.get("safety_tie_photo"):
                    # data уже содержит свежие directorate/ks_region/station/pole_number
                    # из более ранних полей этого же прохода — папка возьмётся из них.
                    new_value = save_record_photo(request.FILES["safety_tie_photo"], data, request)
                elif f.type == "multiselect":
                    new_value = ",".join(request.POST.getlist(f.key))
                else:
                    new_value = request.POST.get(f.key, "").strip()

            old_value = str(data.get(f.key) or "")
            if old_value != new_value:
                changes.append({"field": f.label, "old": old_value, "new": new_value})
            if f.key == "safety_tie":
                replace_managed_photo(old_value, new_value)
            data[f.key] = new_value

        record.data = data
        record.last_modified = timezone.now()
        record.updated_by = account.username
        record.save()
        maybe_attach_defect_card(record)

        if changes:
            Protocol.objects.create(
                uuid=str(uuid.uuid4()),
                record_uuid=record.uuid,
                username=account.username,
                role=account.role,
                changes=changes,
                created_at=timezone.now(),
            )

        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return redirect("web_record_detail", record_uuid=record.uuid)

    dismantled = pole_field_schema.is_dismantled(data)

    def build_row(f):
        if f.type == "file":
            file_field = getattr(record, f.key)
            return {"field": f, "file_url": file_field.url if file_field else None, "editable": False}

        value = f.compute(data) if f.type == "computed" else (data.get(f.key) or "")
        selected = set(str(data.get(f.key) or "").split(",")) if f.type == "multiselect" else None
        options = f.options_for(data) if f.options_for else f.options
        editable = (
            can_edit_record
            and f.type != "computed"
            and pole_field_schema.can_edit_field(account.role, f.key)
            and (f.key == "dismantle_date" or not dismantled)
        )
        return {"field": f, "value": value, "selected": selected, "editable": editable, "options": options}

    sheets = [
        {"name": name, "rows": [build_row(f) for f in fields if not f.enabled_when or f.enabled_when(data)]}
        for name, fields in pole_field_schema.sheets()
    ]

    return render(request, "web/record_detail.html", {
        "record": record, "sheets": sheets, "can_edit_record": can_edit_record,
    })

# --- Раздел «Информация» -----------------------------------------------------

# (slug -> (заголовок, имя url для "назад", подпись "назад")) — общий механизм для
# любых пока не реализованных пунктов меню, независимо от того, в каком разделе они.
STUB_PAGES = {
    "spark_log": ("Журнал учета искровых промежутков", "web_info", "Информация"),
    "diagnostics": ("Приборы диагностики", "web_info", "Информация"),
    "pole_repair": ("Ремонт опор/установка искрового промежутка", "web_work", "Выполнение работ"),
}

ORG_CATEGORY_TITLES = dict(OrgFile.CATEGORY_CHOICES)

@require_web_login
def web_info(request):
    return render(request, "web/info.html", {"account": request.web_account})

@require_web_login
def web_work(request):
    return render(request, "web/work.html", {"account": request.web_account})

def _install_sheets(account, data, locked):
    """Та же раскладка по листам, что и в web_record_detail, но для ещё не сохранённой
    опоры: файловых полей нет (нечего показывать/грузить у совсем новой записи),
    а поля из locked (собственная зона ответственности аккаунта) всегда задизейблены —
    их значение подставляется из аккаунта, а не вводится руками."""
    def build_row(f):
        value = f.compute(data) if f.type == "computed" else (data.get(f.key) or "")
        selected = set(str(data.get(f.key) or "").split(",")) if f.type == "multiselect" else None
        options = f.options_for(data) if f.options_for else f.options
        editable = (
            f.type != "computed"
            and f.key not in locked
            and pole_field_schema.can_edit_field(account.role, f.key)
        )
        return {"field": f, "value": value, "selected": selected, "editable": editable, "options": options}

    return [
        {
            "name": name,
            "rows": [
                build_row(f) for f in fields
                if f.type != "file" and (not f.enabled_when or f.enabled_when(data))
            ],
        }
        for name, fields in pole_field_schema.sheets()
    ]

@require_web_login
def web_install_pole(request):
    """Установка опоры — ручной ввод ОДНОЙ новой опоры (в отличие от add_pole.html,
    который переносит из Excel сразу много). Дирекция/район КС/станция, если они есть
    в собственной зоне ответственности аккаунта, подставляются из него и недоступны
    для правки — остальные поля работают так же, как при обычном редактировании."""
    account = request.web_account
    own_scope_fields = Account.ROLE_SCOPE_FIELDS.get(account.role, [])
    locked = {f: getattr(account, f) for f in own_scope_fields if getattr(account, f)}

    if request.method == "POST":
        data = dict(locked)
        for f in pole_field_schema.FIELDS:
            if f.type in ("computed", "file") or f.key in locked:
                continue
            if not pole_field_schema.can_edit_field(account.role, f.key):
                continue
            if f.enabled_when and not f.enabled_when(data):
                continue
            if f.key == "safety_tie" and request.FILES.get("safety_tie_photo"):
                data[f.key] = save_record_photo(request.FILES["safety_tie_photo"], data, request)
            elif f.type == "multiselect":
                data[f.key] = ",".join(request.POST.getlist(f.key))
            else:
                data[f.key] = request.POST.get(f.key, "").strip()

        if not data.get("pole_number"):
            return render(request, "web/install_pole.html", {
                "sheets": _install_sheets(account, data, locked),
                "error": "Укажите № опоры",
            })

        key = pole_import.dedup_key(data)
        if key is not None and key in pole_import.existing_pole_keys():
            return render(request, "web/install_pole.html", {
                "sheets": _install_sheets(account, data, locked),
                "error": "Такая опора уже есть в базе (дирекция + район КС + станция + номер + индекс совпадают)",
            })

        record = Record.objects.create(
            uuid=str(uuid.uuid4()), data=data,
            last_modified=timezone.now(), updated_by=account.username,
        )
        maybe_attach_defect_card(record)
        return redirect("web_record_detail", record_uuid=record.uuid)

    return render(request, "web/install_pole.html", {"sheets": _install_sheets(account, dict(locked), locked)})

@require_web_login
def web_stub(request, slug):
    entry = STUB_PAGES.get(slug)
    if not entry:
        return render(request, "web/info_stub.html", {"not_found": True})
    title, back_name, back_label = entry
    return render(request, "web/info_stub.html", {
        "title": title, "back_name": back_name, "back_label": back_label,
    })

def _org_level_fields(category: str) -> list:
    return LEVELS[:OrgFile.CATEGORY_DEPTH[category]]

def _org_node_matches_scope(node: dict, level_fields: list, scope: dict) -> bool:
    """node консистентен со scope, если ни одно поле из scope, которое ЕСТЬ в
    level_fields этой категории, ему не противоречит. Поля scope, которых у категории
    вообще нет (например, ks_region у категории уровня «ЭЧ» — Схема питания), не
    проверяются: это единственная сознательная уступка, поскольку аккаунт не хранит
    свою «Дистанцию» отдельно (см. Account.readable_scope_field_names)."""
    for field, value in scope.items():
        if field in level_fields and node.get(field, "") != value:
            return False
    return True

def _org_file_url(category: str, path: dict) -> str:
    level_fields = _org_level_fields(category)
    params = {f: path.get(f, "") for f in level_fields}
    return reverse("web_org_files", kwargs={"category": category}) + "?" + urlencode(params)

@require_web_login
def web_org_files(request, category):
    account = request.web_account
    if category not in OrgFile.CATEGORY_DEPTH:
        return render(request, "web/org_files.html", {"not_found": True})

    level_fields = _org_level_fields(category)
    title = ORG_CATEGORY_TITLES[category]

    own_scope_fields = Account.ROLE_SCOPE_FIELDS.get(account.role, [])
    strict_scope = {f: getattr(account, f) for f in own_scope_fields if getattr(account, f)}
    readable_scope = account.readable_scope_filters()

    # Если в запросе уже пришёл полный путь узла (перешли по ссылке из дерева или
    # с самой файловой страницы) — используем его. Иначе строим путь из того, до чего
    # аккаунт дотягивается сам: непрерывный префикс level_fields, обрывающийся на
    # первом отсутствующем звене (у ЭЧ/ЭЧК это обычно "Дистанция" — её нет в аккаунте).
    if all(request.GET.get(f) for f in level_fields):
        path = {f: request.GET[f] for f in level_fields}
    else:
        path = {}
        for field in level_fields:
            value = readable_scope.get(field, "")
            if not value:
                break
            path[field] = value

    remaining_levels = level_fields[len(path):]

    if remaining_levels:
        records = account.readable_records()
        for field, value in path.items():
            records = records.filter(**{f"data__{field}": value})
        tree_nodes = _build_tree(list(records), remaining_levels, path, lambda p: _org_file_url(category, p))
        return render(request, "web/org_files.html", {
            "title": title, "category": category, "tree_nodes": tree_nodes, "show_tree": True,
        })

    can_view = _org_node_matches_scope(path, level_fields, readable_scope)
    if not can_view:
        return render(request, "web/org_files.html", {"forbidden": True})
    can_edit = _org_node_matches_scope(path, level_fields, strict_scope)

    multiple = category == "power_scheme"
    error = None

    if request.method == "POST":
        if not can_edit:
            return render(request, "web/org_files.html", {"forbidden": True})
        uploaded = request.FILES.get("file")
        if not uploaded:
            error = "Выберите файл"
        else:
            if not multiple:
                for old in OrgFile.objects.filter(category=category, **path):
                    old.file.delete(save=False)
                    old.delete()
            OrgFile.objects.create(
                uuid=str(uuid.uuid4()), category=category, **path,
                file=uploaded, original_name=uploaded.name,
                uploaded_by=account.username, uploaded_at=timezone.now(),
            )
            # PRG как раньше — кроме AJAX-отправки (см. base.html): там редирект не
            # нужен, ниже и так рендерится актуальный список файлов этого узла.
            if request.headers.get("X-Requested-With") != "XMLHttpRequest":
                return redirect(_org_file_url(category, path))

    files = OrgFile.objects.filter(category=category, **path).order_by("uploaded_at")
    node_label = " / ".join(path[f] for f in level_fields)
    return render(request, "web/org_files.html", {
        "title": title, "category": category, "node_label": node_label,
        "path": path, "files": files, "multiple": multiple,
        "can_edit": can_edit, "error": error,
    })

@require_web_login
def web_org_file_delete(request, file_uuid):
    account = request.web_account
    org_file = OrgFile.objects.filter(uuid=file_uuid).first()
    if org_file is None or request.method != "POST":
        return redirect("web_info")

    level_fields = _org_level_fields(org_file.category)
    own_scope_fields = Account.ROLE_SCOPE_FIELDS.get(account.role, [])
    strict_scope = {f: getattr(account, f) for f in own_scope_fields if getattr(account, f)}
    node = {f: getattr(org_file, f) for f in level_fields}
    category = org_file.category

    if _org_node_matches_scope(node, level_fields, strict_scope):
        org_file.file.delete(save=False)
        org_file.delete()

    return redirect(_org_file_url(category, node))

# --- Демонтаж опор -------------------------------------------------------------

def _dismantle_station_url(path: dict) -> str:
    return reverse("web_dismantle_station") + "?" + urlencode({
        "directorate": path.get("directorate", ""),
        "ks_region": path.get("ks_region", ""),
        "station": path.get("station", ""),
    })

@require_web_login
def web_dismantle(request):
    """Обзор для демонтажа — тот же охват, что и в Книге опор (readable_records: ЭЧ
    видит и соседние ЭЧ/ЭЧК своей Дирекции), лист ведёт не в полный редактор записи,
    а на список опор станции с кнопкой демонтажа."""
    account = request.web_account
    readable_fields = account.readable_scope_field_names()
    scoped_positions = [LEVELS.index(f) for f in readable_fields if f in LEVELS]
    remaining_levels = LEVELS[max(scoped_positions, default=-1) + 1:]
    own_path = {f: getattr(account, f) for f in readable_fields}

    if not remaining_levels:
        return redirect(_dismantle_station_url(own_path))

    tree_nodes = _build_tree(list(account.readable_records()), remaining_levels, own_path, _dismantle_station_url)
    return render(request, "web/dismantle.html", {"show_tree": True, "tree_nodes": tree_nodes})

@require_web_login
def web_dismantle_station(request):
    account = request.web_account
    directorate = request.GET.get("directorate", "")
    ks_region = request.GET.get("ks_region", "")
    station = request.GET.get("station", "")

    records = account.readable_records()
    if directorate:
        records = records.filter(data__directorate=directorate)
    if ks_region:
        records = records.filter(data__ks_region=ks_region)
    if station:
        records = records.filter(data__station=station)

    # Уже демонтированные опоры тут делать больше нечего.
    active = [r for r in records if not pole_field_schema.is_dismantled(r.data if isinstance(r.data, dict) else {})]
    odd, even = _split_odd_even(active)

    def annotate(records):
        return [{"record": r, "can_edit": account.can_edit_record(r)} for r in records]

    return render(request, "web/dismantle.html", {
        "station": station or "(не указано)",
        "items_odd": annotate(odd), "items_even": annotate(even),
    })

@require_web_login
def web_dismantle_pole(request, record_uuid):
    account = request.web_account
    record = account.readable_records().filter(uuid=record_uuid).first()
    if record is None or request.method != "POST" or not account.can_edit_record(record):
        return redirect("web_dismantle")

    data = dict(record.data) if isinstance(record.data, dict) else {}
    if not pole_field_schema.is_dismantled(data):
        moscow_now = timezone.now().astimezone(ZoneInfo("Europe/Moscow"))
        new_value = moscow_now.strftime("%d.%m.%Y %H:%M МСК")
        old_value = str(data.get("dismantle_date") or "")

        data["dismantle_date"] = new_value
        record.data = data
        record.last_modified = timezone.now()
        record.updated_by = account.username
        record.save()

        Protocol.objects.create(
            uuid=str(uuid.uuid4()), record_uuid=record.uuid,
            username=account.username, role=account.role,
            changes=[{"field": "Год демонтажа (архив)", "old": old_value, "new": new_value}],
            created_at=timezone.now(),
        )

    return redirect(_dismantle_station_url({
        "directorate": data.get("directorate", ""),
        "ks_region": data.get("ks_region", ""),
        "station": data.get("station", ""),
    }))

# --- Планирование → Опорное хозяйство → Диагностирование опор ------------------

MONTHS = [
    (1, "Январь"), (2, "Февраль"), (3, "Март"), (4, "Апрель"),
    (5, "Май"), (6, "Июнь"), (7, "Июль"), (8, "Август"),
    (9, "Сентябрь"), (10, "Октябрь"), (11, "Ноябрь"), (12, "Декабрь"),
]
MONTH_NAMES = dict(MONTHS)

DIAGNOSTICS_METRICS = [
    ("metal_above", "Обследование надземной части металлических"),
    ("concrete_above", "Обследование надземной части железобетонных"),
    ("below", "Обследование подземной части"),
    ("potential", "Измерение потенциальной зоны"),
    ("resistance", "Измерение сопротивления"),
]

@require_web_login
def web_planning(request):
    return render(request, "web/planning.html", {"account": request.web_account})

@require_web_login
def web_pole_economy(request):
    return render(request, "web/pole_economy.html", {"account": request.web_account})

def _diagnostics_years(account):
    """Года планирования — из уже проставленных на опорах "год очередной проверки"
    полей, ПЛЮС года, для которых уже что-то сохранили в InspectionPlan вручную (месяц
    или галочку) без совпадения по этим полям — иначе такой сохранённый год было бы
    нечем найти в списке при следующем заходе. Список можно расширить и дальше,
    введя год руками (см. шаблон)."""
    records = list(account.readable_records())
    years = set()
    for record in records:
        data = record.data if isinstance(record.data, dict) else {}
        for field in ("next_check_year_above", "next_check_year_below", "next_check_year_r"):
            raw = str(data.get(field) or "").strip()
            if raw.isdigit() and len(raw) == 4:
                years.add(int(raw))
    years.update(
        InspectionPlan.objects.filter(record_uuid__in=[r.uuid for r in records]).values_list("year", flat=True)
    )
    return sorted(years)



def _diagnostics_station_url(year, path: dict) -> str:
    return reverse("web_diagnostics_station") + "?" + urlencode({
        "year": year,
        "directorate": path.get("directorate", ""),
        "ks_region": path.get("ks_region", ""),
        "station": path.get("station", ""),
    })


@require_web_login
def web_diagnostics(request):
    account = request.web_account
    year_raw = request.GET.get("year", "").strip()

    if not year_raw.isdigit():
        return render(request, "web/diagnostics.html", {
            "choose_year": True, "years": _diagnostics_years(account),
        })

    year = int(year_raw)
    readable_fields = account.readable_scope_field_names()
    scoped_positions = [LEVELS.index(f) for f in readable_fields if f in LEVELS]
    remaining_levels = LEVELS[max(scoped_positions, default=-1) + 1:]
    own_path = {f: getattr(account, f) for f in readable_fields}

    if not remaining_levels:
        return redirect(_diagnostics_station_url(year, own_path))

    tree_nodes = _build_tree(
        list(account.readable_records()), remaining_levels, own_path,
        lambda p: _diagnostics_station_url(year, p),
    )
    return render(request, "web/diagnostics.html", {"show_tree": True, "year": year, "tree_nodes": tree_nodes})

@require_web_login
def web_diagnostics_station(request):
    account = request.web_account
    year_raw = request.GET.get("year", "").strip()
    if not year_raw.isdigit():
        return redirect("web_diagnostics")
    year = int(year_raw)
    year_str = str(year)

    directorate = request.GET.get("directorate", "")
    ks_region = request.GET.get("ks_region", "")
    station = request.GET.get("station", "")

    records = account.readable_records()
    if directorate:
        records = records.filter(data__directorate=directorate)
    if ks_region:
        records = records.filter(data__ks_region=ks_region)
    if station:
        records = records.filter(data__station=station)
    records = [r for r in records if not pole_field_schema.is_dismantled(r.data if isinstance(r.data, dict) else {})]

    # Подстановка месяца сразу везде, где он ещё не выбран — только предзаполняет форму
    # ниже (см. diagnostics_station.html), реально сохраняется только после «Сохранить».
    bulk_month_raw = request.GET.get("bulk_month", "").strip()
    bulk_month = int(bulk_month_raw) if bulk_month_raw.isdigit() and 1 <= int(bulk_month_raw) <= 12 else None

    def build_rows():
        """Вынесено в функцию, чтобы можно было пересобрать после сохранения — save()
        меняет только базу, а не уже построенный список rows."""
        plans = {
            p.record_uuid: p
            for p in InspectionPlan.objects.filter(year=year, record_uuid__in=[r.uuid for r in records])
        }
        rows = []
        for record in records:
            data = record.data if isinstance(record.data, dict) else {}
            plan = plans.get(record.uuid)
            can_edit = account.can_edit_record(record)

            above_due = str(data.get("next_check_year_above") or "").strip() == year_str
            below_due = str(data.get("next_check_year_below") or "").strip() == year_str
            is_dc = data.get("current_type") == "постоянный"
            needs_potential = plan.needs_potential_zone if plan else False

            # Сопротивление — как и потенциальная зона, не только автотриггер по
            # next_check_year_r, но и ручной чекбокс (иначе опору, у которой этот год
            # ещё не проставлен, вообще нечем было бы добавить в план).
            
            r_due = str(data.get("next_check_year_r") or "").strip() == year_str
            needs_resistance = plan.needs_resistance if plan else False
            resistance_needed = r_due or needs_resistance

            month = plan.month if plan else None
            if month is None and bulk_month and can_edit:
                month = bulk_month

            # В ИТОГО опора попадает и если ей просто назначен месяц, даже без
            # отмеченного конкретного вида обследования — план на неё уже есть. В
            # строки конкретных видов она всё равно не попадёт, пока сам вид не отмечен.
            relevant = above_due or below_due or resistance_needed or needs_potential or month is not None

            rows.append({
                "record": record, "can_edit": can_edit,
                "above_due": above_due, "below_due": below_due,
                "resistance_needed": resistance_needed,
                "is_dc": is_dc, "needs_potential": needs_potential, "relevant": relevant,
                "metal": pole_field_schema.is_metal_pole(data.get("pole_mark")),
                "anchor": pole_field_schema.is_anchor(data.get("purpose")),
                "month": month, "month_name": MONTH_NAMES.get(month, ""),
            })
        return plans, rows

    plans, rows = build_rows()

    if request.method == "POST":
        for row in rows:
            if not row["can_edit"]:
                continue
            record = row["record"]
            month_raw = request.POST.get(f"month_{record.uuid}", "").strip()
            new_month = int(month_raw) if month_raw.isdigit() and 1 <= int(month_raw) <= 12 else None
            new_potential = bool(request.POST.get(f"potential_{record.uuid}")) if row["is_dc"] else False
            new_resistance = bool(request.POST.get(f"resistance_{record.uuid}"))

            plan = plans.get(record.uuid)
            if plan is None:
                if new_month is None and not new_potential and not new_resistance:
                    continue
                plan = InspectionPlan(uuid=str(uuid.uuid4()), record_uuid=record.uuid, year=year)
            plan.month = new_month
            plan.needs_potential_zone = new_potential
            plan.needs_resistance = new_resistance
            plan.updated_by = account.username
            plan.updated_at = timezone.now()
            plan.save()

        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return redirect(_diagnostics_station_url(year, {
                "directorate": directorate, "ks_region": ks_region, "station": station,
            }))
        plans, rows = build_rows()

    # Правая (сводная) таблица целиком вычисляется из тех же rows — независимого
    # хранения месяцев для неё нет, иначе две точки правды разойдутся.
    metric_hits = {key: [] for key, _ in DIAGNOSTICS_METRICS}
    for row in rows:
        if row["above_due"]:
            metric_hits["metal_above" if row["metal"] else "concrete_above"].append(row)
        if row["below_due"]:
            metric_hits["below"].append(row)
        if row["resistance_needed"]:
            metric_hits["resistance"].append(row)
        if row["needs_potential"]:
            metric_hits["potential"].append(row)

    summary_rows = []
    for key, label in DIAGNOSTICS_METRICS:
        hits = metric_hits[key]
        by_month = [0] * 12
        for row in hits:
            if row["month"]:
                by_month[row["month"] - 1] += 1
        summary_rows.append({"label": label, "total": len(hits), "by_month": by_month})

    # ИТОГО — уникальные опоры (см. накладку видов обследования на одной опоре), а не
    # сумма строк выше.
    relevant_rows = [row for row in rows if row["relevant"]]
    total_by_month = [0] * 12
    for row in relevant_rows:
        if row["month"]:
            total_by_month[row["month"] - 1] += 1
    summary_rows.append({"label": "ИТОГО", "total": len(relevant_rows), "by_month": total_by_month})

    return render(request, "web/diagnostics_station.html", {
        "year": year, "station": station or "(не указано)",
        "directorate": directorate, "ks_region": ks_region,
        "rows": rows, "summary_rows": summary_rows, "months": MONTHS,
    })