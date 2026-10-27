import uuid
from django.db import models
from .record_paths import record_folder, safe_segment

def _defect_card_upload_path(instance, filename):
    data = instance.data if isinstance(instance.data, dict) else {}
    return f"records/{record_folder(data)}/{filename}"

def _org_file_upload_path(instance, filename):
    segments = [safe_segment(instance.directorate)]
    for field in ("distance", "ks_region", "station"):
        value = getattr(instance, field)
        if value:
            segments.append(safe_segment(value))
    segments.append(instance.category)
    return f"org_files/{'/'.join(segments)}/{filename}"

class Account(models.Model):
    ROLE_CHOICES = [("TE", "ТЭ"), ("NTE", "НТЭ"), ("ECh", "ЭЧ"), ("EChK", "ЭЧК")]

    # Поля принадлежности сотрудника, по которым фильтруются записи при выдаче с сервера.
    # Совпадают по ключам с PoleFieldSchema (мобильное приложение), поэтому фильтрация
    # идёт напрямую по Record.data без промежуточного маппинга.
    ROLE_SCOPE_FIELDS = {
        "TE": [],
        "NTE": ["directorate"],
        "ECh": ["directorate", "ks_region"],
        "EChK": ["directorate", "ks_region", "station"],
    }

    uuid = models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True)
    password_hash = models.CharField(max_length=255)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    full_name = models.CharField("ФИО", max_length=255, blank=True, default="")
    directorate = models.CharField("Дирекция по энергообеспечению", max_length=255, blank=True, default="")
    ks_region = models.CharField("Район контактной сети", max_length=255, blank=True, default="")
    station = models.CharField("Станция, Перегон", max_length=255, blank=True, default="")
    created_by = models.CharField(max_length=150, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} ({self.role})"

    def scope_filters(self) -> dict:
        """Непустые {поле: значение} из ROLE_SCOPE_FIELDS для этой роли — используются
        и при валидации формы регистрации, и при фильтрации Record по данному аккаунту.
        Это СТРОГАЯ зона ответственности — как раз она определяет, что аккаунт может
        РЕДАКТИРОВАТЬ (см. can_edit_record)."""
        fields = self.ROLE_SCOPE_FIELDS.get(self.role, [])
        return {field: getattr(self, field) for field in fields if getattr(self, field)}

    def visible_records(self):
        """Record, относящиеся к строгой зоне ответственности аккаунта (для API синхронизации
        и для любых операций редактирования в веб-интерфейсе)."""
        qs = Record.objects.all()
        for field, value in self.scope_filters().items():
            qs = qs.filter(**{f"data__{field}": value})
        return qs

    def readable_scope_field_names(self) -> list:
        """Список полей (не значений) строгой зоны ответственности — как ROLE_SCOPE_FIELDS,
        но для роли ЭЧ (и только для неё) без ks_region: такие сотрудники могут ПРОСМАТРИВАТЬ
        (не редактировать) соседние ЭЧ и ЭЧК в пределах своей же Дирекции."""
        fields = list(self.ROLE_SCOPE_FIELDS.get(self.role, []))
        if self.role == "ECh":
            fields = [f for f in fields if f != "ks_region"]
        return fields

    def readable_scope_filters(self) -> dict:
        """Как scope_filters(), но по readable_scope_field_names() — используется везде,
        где данные только ПОКАЗЫВАЮТСЯ (дерево, поиск, просмотр записи), а не редактируются."""
        fields = self.readable_scope_field_names()
        return {field: getattr(self, field) for field in fields if getattr(self, field)}

    def readable_records(self):
        """Record, которые аккаунт может ПРОСМАТРИВАТЬ — шире visible_records() только для
        роли ЭЧ (видит соседей по своей Дирекции). Для остальных ролей совпадает с
        visible_records(). НЕ использовать для проверки прав на редактирование."""
        qs = Record.objects.all()
        for field, value in self.readable_scope_filters().items():
            qs = qs.filter(**{f"data__{field}": value})
        return qs

    def can_edit_record(self, record) -> bool:
        """Строгая проверка: запись редактируема, только если она входит в scope_filters()
        аккаунта (т.е. видна и через visible_records()), а не просто через readable_records()."""
        data = record.data if isinstance(record.data, dict) else {}
        for field, value in self.scope_filters().items():
            if data.get(field) != value:
                return False
        return True

class Record(models.Model):
    uuid = models.CharField(max_length=36, unique=True, db_index=True)
    data = models.JSONField()
    last_modified = models.DateTimeField()
    updated_by = models.CharField(max_length=150, null=True, blank=True)
    defect_card = models.FileField(upload_to=_defect_card_upload_path, null=True, blank=True)

    def __str__(self):
        pole = self.data.get("pole_number") if isinstance(self.data, dict) else None
        station = self.data.get("station") if isinstance(self.data, dict) else None
        return f"№{pole or '?'} — {station or self.uuid}"

class OrgFile(models.Model):
    """Файлы, привязанные не к конкретной опоре, а к организационному узлу (разделы
    меню «Информация»): Схема питания и секционирования — на уровне ЭЧ (несколько
    файлов), Паспорт ЭЧК / Организационная структура — на уровне ЭЧК (один файл),
    План контактной сети — на уровне станции/перегона (один файл)."""

    CATEGORY_CHOICES = [
        ("power_scheme", "Схема питания и секционирования"),
        ("echk_passport", "Паспорт ЭЧК"),
        ("network_plan", "План контактной сети"),
        ("org_structure", "Организационная структура"),
    ]

    # Сколько уровней из views_web.LEVELS (directorate, distance, ks_region, station)
    # относятся к узлу этой категории — определяет и глубину дерева до файловой
    # страницы, и то, какие поля учитываются при проверке прав редактирования.
    CATEGORY_DEPTH = {
        "power_scheme": 2,
        "echk_passport": 3,
        "network_plan": 4,
        "org_structure": 3,
    }

    uuid = models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    directorate = models.CharField(max_length=255, blank=True, default="")
    distance = models.CharField(max_length=255, blank=True, default="")
    ks_region = models.CharField(max_length=255, blank=True, default="")
    station = models.CharField(max_length=255, blank=True, default="")
    file = models.FileField(upload_to=_org_file_upload_path)
    original_name = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.CharField(max_length=150, blank=True, default="")
    uploaded_at = models.DateTimeField()

    def __str__(self):
        return f"{self.get_category_display()} — {self.original_name or self.file.name}"

class InspectionPlan(models.Model):
    """Годовой план обследования опоры — данные, которые не являются постоянным
    атрибутом самой опоры (Record.data), а привязаны к конкретному году планирования
    (раздел «Планирование» → «Опорное хозяйство» → «Диагностирование опор»).
    record_uuid — тот же паттерн, что и Protocol.record_uuid: обычный CharField, а не
    ForeignKey, чтобы не тащить связь ради простого сопоставления по uuid."""
    uuid = models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False)
    record_uuid = models.CharField(max_length=36, db_index=True)
    year = models.IntegerField()
    month = models.IntegerField(null=True, blank=True)
    needs_potential_zone = models.BooleanField(default=False)
    needs_resistance = models.BooleanField(default=False)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    updated_at = models.DateTimeField()

    class Meta:
        unique_together = [("record_uuid", "year")]

    def __str__(self):
        return f"{self.record_uuid} — {self.year}"


class Protocol(models.Model):
    uuid = models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False)
    record_uuid = models.CharField(max_length=36, db_index=True)
    username = models.CharField(max_length=150)
    role = models.CharField(max_length=10)
    changes = models.JSONField()
    created_at = models.DateTimeField()
    pdf = models.FileField(upload_to="protocols/", null=True, blank=True)

    def __str__(self):
        return f"Протокол {self.uuid} ({self.record_uuid})"

class ServerConfig(models.Model):
    server_address = models.CharField(max_length=255, blank=True, default="")
    updated_by = models.CharField(max_length=150, blank=True, default="")
    updated_at = models.DateTimeField()

    def __str__(self):
        return self.server_address or "(не задан)"