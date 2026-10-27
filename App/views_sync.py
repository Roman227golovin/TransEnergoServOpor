import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import Account, Record, ServerConfig
from .auth import require_auth
from .defect_card import maybe_attach_defect_card
from .photo_upload import save_record_photo, replace_managed_photo


def _record_out(record):
    return {"uuid": record.uuid, "data": record.data, "last_modified": record.last_modified.isoformat()}


def _current_account(request):
    return Account.objects.filter(uuid=request.current_account["sub"]).first()


@csrf_exempt
@require_http_methods(["POST"])
@require_auth
def push_records(request):
    payload = json.loads(request.body)
    updated = 0

    for incoming in payload:
        incoming_last_modified = parse_datetime(incoming["last_modified"])
        if incoming_last_modified is None:
            continue

        existing = Record.objects.filter(uuid=incoming["uuid"]).first()
        if existing is None:
            new_record = Record.objects.create(
                uuid=incoming["uuid"],
                data=incoming["data"],
                last_modified=incoming_last_modified,
                updated_by=request.current_account["username"],
            )
            maybe_attach_defect_card(new_record)
            updated += 1
        elif incoming_last_modified > existing.last_modified:
            old_data = existing.data if isinstance(existing.data, dict) else {}
            new_data = incoming["data"] if isinstance(incoming["data"], dict) else {}
            replace_managed_photo(old_data.get("safety_tie") or "", new_data.get("safety_tie") or "")

            existing.data = incoming["data"]
            existing.last_modified = incoming_last_modified
            existing.updated_by = request.current_account["username"]
            existing.save()
            maybe_attach_defect_card(existing)
            updated += 1

    return JsonResponse({"updated": updated})


@require_http_methods(["GET"])
@require_auth
def pull_records(request):
    account = _current_account(request)
    if account is None:
        return JsonResponse({"detail": "Аккаунт не найден"}, status=401)

    qs = account.visible_records()
    since = request.GET.get("since")
    if since:
        since_dt = parse_datetime(since)
        if since_dt:
            qs = qs.filter(last_modified__gt=since_dt)
    return JsonResponse([_record_out(r) for r in qs], safe=False)


@csrf_exempt
@require_http_methods(["POST"])
@require_auth
def upload_photo(request):
    uploaded = request.FILES.get("photo")
    if uploaded is None:
        return JsonResponse({"detail": "Файл не передан"}, status=400)
    if not (uploaded.content_type or "").startswith("image/"):
        return JsonResponse({"detail": "Ожидается изображение"}, status=400)

    # Телефон присылает их же вместе с фото, чтобы сервер разложил файл в папку
    # той же опоры (Дирекция/Район КС/Станция/Опора), как на сайте.
    location = {
        "directorate": request.POST.get("directorate", ""),
        "ks_region": request.POST.get("ks_region", ""),
        "station": request.POST.get("station", ""),
        "pole_number": request.POST.get("pole_number", ""),
    }
    url = save_record_photo(uploaded, location, request)
    return JsonResponse({"url": url})


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_auth
def server_address(request):
    """Адрес сервера, разосланный ТЭ (см. models.ServerConfig). GET — любой
    аккаунт подтягивает актуальное значение при синхронизации; POST — сменить
    его может только ТЭ, остальным ролям возвращаем 403."""
    if request.method == "POST":
        if request.current_account.get("role") != "TE":
            return JsonResponse({"detail": "Адрес сервера может менять только ТЭ"}, status=403)

        payload = json.loads(request.body)
        address = (payload.get("server_address") or "").strip()
        if not address:
            return JsonResponse({"detail": "Укажите адрес сервера"}, status=400)

        config = ServerConfig.objects.first() or ServerConfig()
        config.server_address = address
        config.updated_by = request.current_account["username"]
        config.updated_at = timezone.now()
        config.save()
        return JsonResponse({"server_address": config.server_address})

    config = ServerConfig.objects.first()
    return JsonResponse({"server_address": config.server_address if config else ""})


@require_http_methods(["GET"])
@require_auth
def search_records(request):
    account = _current_account(request)
    if account is None:
        return JsonResponse({"detail": "Аккаунт не найден"}, status=401)

    qs = account.visible_records()
    station = request.GET.get("station")
    distance = request.GET.get("distance")
    pole_number = request.GET.get("pole_number")

    if station:
        qs = qs.filter(data__station__icontains=station)
    if distance:
        qs = qs.filter(data__distance__icontains=distance)
    if pole_number:
        qs = qs.filter(data__pole_number=int(pole_number))

    return JsonResponse([_record_out(r) for r in qs], safe=False)
