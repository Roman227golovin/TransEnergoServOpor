import json
import uuid as uuid_lib
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.files.base import ContentFile
from django.utils.dateparse import parse_datetime
from .models import Protocol
from .auth import require_auth


@csrf_exempt
@require_http_methods(["POST"])
@require_auth
def upload_protocol(request):
    protocol_uuid = str(uuid_lib.uuid4())
    pdf_file = request.FILES.get("pdf")

    protocol = Protocol(
        uuid=protocol_uuid,
        record_uuid=request.POST.get("record_uuid"),
        username=request.POST.get("username"),
        role=request.POST.get("role"),
        changes=json.loads(request.POST.get("changes")),
        created_at=parse_datetime(request.POST.get("created_at")),
    )
    if pdf_file:
        protocol.pdf.save(f"{protocol_uuid}.pdf", ContentFile(pdf_file.read()), save=False)
    protocol.save()

    return JsonResponse({"uuid": protocol_uuid})


@require_http_methods(["GET"])
@require_auth
def list_protocols(request):
    protocols = Protocol.objects.all()
    return JsonResponse([{
        "uuid": p.uuid,
        "record_uuid": p.record_uuid,
        "username": p.username,
        "role": p.role,
        "changes": p.changes,
        "created_at": p.created_at.isoformat(),
        "pdf_path": p.pdf.url if p.pdf else None,
    } for p in protocols], safe=False)