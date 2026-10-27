import uuid
from django.core.management.base import BaseCommand
from django.utils import timezone
from passlib.context import CryptContext
from App.models import Account, Record

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SAMPLE_RECORDS = [
    {"directorate": "Дирекция №1", "distance": "ЭЧ-1", "ks_region": "ЭЧК-1", "station": "ст. Северная", "km": 12, "pk": 3, "m": 50, "track_number": 1, "current_type": "переменный", "pole_number": 101, "pole_mark": "СЦ-4А", "purpose": "промежуточная", "install_year": 2005},
    {"directorate": "Дирекция №1", "distance": "ЭЧ-1", "ks_region": "ЭЧК-1", "station": "ст. Северная", "km": 12, "pk": 4, "m": 120, "track_number": 1, "current_type": "переменный", "pole_number": 102, "pole_mark": "СЦ-4А", "purpose": "анкерная", "install_year": 2005},
    {"directorate": "Дирекция №1", "distance": "ЭЧ-2", "ks_region": "ЭЧК-2", "station": "ст. Южная", "km": 45, "pk": 1, "m": 10, "track_number": 2, "current_type": "постоянный", "pole_number": 201, "pole_mark": "СЦ-6", "purpose": "переходная", "install_year": 1998},
    {"directorate": "Дирекция №1", "distance": "ЭЧ-2", "ks_region": "ЭЧК-2", "station": "ст. Южная", "km": 45, "pk": 2, "m": 200, "track_number": 2, "current_type": "постоянный", "pole_number": 202, "pole_mark": "СЦ-6", "purpose": "промежуточная", "install_year": 1998},
    {"directorate": "Дирекция №2", "distance": "ЭЧ-3", "ks_region": "ЭЧК-3", "station": "ст. Заречная", "km": 78, "pk": 5, "m": 300, "track_number": 1, "current_type": "переменный", "pole_number": 301, "pole_mark": "ЖБК", "purpose": "фидерная", "install_year": 2012},
    {"directorate": "Дирекция №2", "distance": "ЭЧ-3", "ks_region": "ЭЧК-3", "station": "ст. Заречная", "km": 78, "pk": 6, "m": 400, "track_number": 1, "current_type": "переменный", "pole_number": 302, "pole_mark": "ЖБК", "purpose": "промежуточная", "install_year": 2012},
    {"directorate": "Дирекция №2", "distance": "ЭЧ-3", "ks_region": "ЭЧК-4", "station": "перегон Заречная — Луговая", "km": 80, "pk": 1, "m": 0, "track_number": 1, "current_type": "переменный", "pole_number": 303, "pole_mark": "СЦ-4А", "purpose": "анкерная", "install_year": 2015},
    {"directorate": "Дирекция №3", "distance": "ЭЧ-4", "ks_region": "ЭЧК-5", "station": "ст. Луговая", "km": 95, "pk": 2, "m": 150, "track_number": 3, "current_type": "постоянный", "pole_number": 401, "pole_mark": "СЦ-6", "purpose": "переходная", "install_year": 2001},
    {"directorate": "Дирекция №3", "distance": "ЭЧ-4", "ks_region": "ЭЧК-5", "station": "ст. Луговая", "km": 95, "pk": 3, "m": 250, "track_number": 3, "current_type": "постоянный", "pole_number": 402, "pole_mark": "СЦ-6", "purpose": "промежуточная", "install_year": 2001},
    {"directorate": "Дирекция №3", "distance": "ЭЧ-4", "ks_region": "ЭЧК-5", "station": "ст. Луговая", "km": 96, "pk": 1, "m": 30, "track_number": 3, "current_type": "постоянный", "pole_number": 403, "pole_mark": "ЖБК", "purpose": "фидерная", "install_year": 2001},
]

# ТЭ зоной вообще не ограничивается (видит все записи). Внутри остальных ролей часть
# аккаунтов намеренно делят одну и ту же зону ответственности, а часть — разные, чтобы на
# фильтрации записей было видно и совпадение, и различие выдачи.
SAMPLE_ACCOUNTS = [
    {"username": "te_1", "full_name": "Иванов Иван Иванович", "role": "TE"},
    {"username": "te_2", "full_name": "Петров Пётр Петрович", "role": "TE"},

    {"username": "nte_1", "full_name": "Кузнецов Алексей Викторович", "role": "NTE", "directorate": "Дирекция №1"},
    {"username": "nte_2", "full_name": "Смирнова Ольга Николаевна", "role": "NTE", "directorate": "Дирекция №1"},
    {"username": "nte_3", "full_name": "Попов Дмитрий Сергеевич", "role": "NTE", "directorate": "Дирекция №2"},

    {"username": "ech_1", "full_name": "Соколов Андрей Павлович", "role": "ECh", "directorate": "Дирекция №1", "ks_region": "ЭЧК-1"},
    {"username": "ech_2", "full_name": "Волкова Мария Игоревна", "role": "ECh", "directorate": "Дирекция №1", "ks_region": "ЭЧК-1"},
    {"username": "ech_3", "full_name": "Морозов Николай Фёдорович", "role": "ECh", "directorate": "Дирекция №1", "ks_region": "ЭЧК-2"},

    {"username": "echk_1", "full_name": "Лебедев Виктор Анатольевич", "role": "EChK", "directorate": "Дирекция №3", "ks_region": "ЭЧК-5", "station": "ст. Луговая"},
    {"username": "echk_2", "full_name": "Новикова Татьяна Владимировна", "role": "EChK", "directorate": "Дирекция №3", "ks_region": "ЭЧК-5", "station": "ст. Луговая"},
    {"username": "echk_3", "full_name": "Козлов Роман Дмитриевич", "role": "EChK", "directorate": "Дирекция №1", "ks_region": "ЭЧК-1", "station": "ст. Северная"},
]

SAMPLE_PASSWORD = "1111"


class Command(BaseCommand):
    help = "Создаёт тестовые аккаунты TE/NTE/ECh/EChK и записи для проверки фильтрации по зоне ответственности"

    def handle(self, *args, **options):
        accounts_created = 0
        for account in SAMPLE_ACCOUNTS:
            if Account.objects.filter(username=account["username"]).exists():
                continue
            Account.objects.create(
                password_hash=pwd_context.hash(SAMPLE_PASSWORD),
                created_by="seed_records",
                **account,
            )
            accounts_created += 1
        self.stdout.write(self.style.SUCCESS(f"Создано {accounts_created} тестовых аккаунтов (пароль у всех: {SAMPLE_PASSWORD})"))

        records_created = 0
        for data in SAMPLE_RECORDS:
            if Record.objects.filter(data__pole_number=data["pole_number"]).exists():
                continue
            Record.objects.create(
                uuid=str(uuid.uuid4()),
                data=data,
                last_modified=timezone.now(),
                updated_by="seed_records",
            )
            records_created += 1
        self.stdout.write(self.style.SUCCESS(f"Создано {records_created} тестовых записей"))
