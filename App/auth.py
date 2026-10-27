import jwt
from datetime import datetime, timedelta, timezone
from functools import wraps
from django.conf import settings
from django.http import JsonResponse


def create_access_token(account_uuid: str, username: str, role: str) -> str:
    payload = {
        "sub": account_uuid,
        "username": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])


def get_current_account(request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not token:
        return None
    try:
        return decode_access_token(token)
    except Exception:
        return None


def require_auth(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        current = get_current_account(request)
        if current is None:
            return JsonResponse({"detail": "Недействительный токен"}, status=401)
        request.current_account = current
        return view_func(request, *args, **kwargs)
    return wrapper