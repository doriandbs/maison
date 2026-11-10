from django.http import HttpRequest


def ip_cliente(request: HttpRequest) -> str:
    """Adresse du client derrière nginx, qui écrase X-Forwarded-For (deploy/nginx/maison.conf)."""
    transmis = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmis:
        return transmis.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
