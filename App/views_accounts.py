import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from passlib.context import CryptContext
from .models import Account
from .auth import create_access_token, require_auth

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ROLE_HIERARCHY = {
    "TE": ["TE", "NTE", "ECh", "EChK"],
    "NTE": ["ECh", "EChK"],
}

SCOPE_FIELD_LABELS = {
    "directorate": "Дирекция по энергообеспечению",
    "ks_region": "Район контактной сети",
    "station": "Станция, Перегон",
}


@csrf_exempt
@require_http_methods(["POST"])
def login(request):
    body = json.loads(request.body)
    try:
        account = Account.objects.get(username=body.get("username"))
    except Account.DoesNotExist:
        return JsonResponse({"detail": "Неверный логин или пароль"}, status=401)

    if not pwd_context.verify(body.get("password", ""), account.password_hash):
        return JsonResponse({"detail": "Неверный логин или пароль"}, status=401)

    token = create_access_token(account.uuid, account.username, account.role)
    return JsonResponse({
        "token": token,
        "role": account.role,
        "username": account.username,
        "uuid": account.uuid,
    })


@csrf_exempt
@require_http_methods(["POST"])
@require_auth
def register(request):
    body = json.loads(request.body)
    username, password, role = body.get("username"), body.get("password"), body.get("role")
    full_name = (body.get("full_name") or "").strip()

    creator_role = request.current_account["role"]
    allowed_roles = ROLE_HIERARCHY.get(creator_role)

    if not allowed_roles:
        return JsonResponse({"detail": "У вас нет прав на регистрацию аккаунтов"}, status=403)
    if role not in allowed_roles:
        return JsonResponse({"detail": f"Роль {creator_role} не может создавать аккаунты с ролью {role}"}, status=403)
    if Account.objects.filter(username=username).exists():
        return JsonResponse({"detail": "Такой логин уже существует"}, status=409)
    if not full_name:
        return JsonResponse({"detail": "Укажите ФИО"}, status=400)

    scope_values = {}
    for field in Account.ROLE_SCOPE_FIELDS.get(role, []):
        value = (body.get(field) or "").strip()
        if not value:
            return JsonResponse({"detail": f"Укажите поле «{SCOPE_FIELD_LABELS[field]}»"}, status=400)
        scope_values[field] = value

    new_account = Account.objects.create(
        username=username,
        password_hash=pwd_context.hash(password),
        role=role,
        full_name=full_name,
        created_by=request.current_account["sub"],
        **scope_values,
    )
    return JsonResponse({"uuid": new_account.uuid, "username": new_account.username, "role": new_account.role})
