from django.core.management.base import BaseCommand
from passlib.context import CryptContext
from App.models import Account

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Command(BaseCommand):
    help = "Создаёт первый аккаунт TE"

    def handle(self, *args, **options):
        if Account.objects.filter(username="admin").exists():
            self.stdout.write("Аккаунт admin уже существует")
            return
        Account.objects.create(username="admin", password_hash=pwd_context.hash("1111"), role="TE")
        self.stdout.write(self.style.SUCCESS("Создан аккаунт admin (TE)"))