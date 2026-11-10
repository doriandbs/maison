from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from .sante import base_joignable


def sante(request: HttpRequest) -> JsonResponse:
    if base_joignable():
        return JsonResponse({"etat": "ok"})
    return JsonResponse({"etat": "erreur", "detail": "base de données injoignable"}, status=503)


def trop_de_requetes(request: HttpRequest, exception: Exception) -> HttpResponse:
    return render(request, "socle/trop_de_requetes.html", status=429)
