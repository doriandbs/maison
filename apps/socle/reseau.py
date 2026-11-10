from django.http import HttpRequest


def ip_cliente(request: HttpRequest) -> str:
    """Adresse du client derrière Caddy, qui écrase X-Forwarded-For pour les clients non fiables."""
    transmis = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmis:
        return transmis.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
