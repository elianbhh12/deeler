import requests
import pytest

import core.ado_client as ado_client


def test_reintenta_ante_falla_transitoria_y_despues_funciona(monkeypatch):
    """Simula justo el patrón reportado: falla con DNS/conexión un par de
    veces (VPN corporativa bajo carga) y la siguiente sí resuelve — no debe
    tirar la excepción en el primer intento fallido."""
    llamadas = {"n": 0}

    def fake_get(url, headers, timeout):
        llamadas["n"] += 1
        if llamadas["n"] < 3:
            raise requests.exceptions.ConnectionError("Failed to resolve (simulado)")
        return "respuesta-ok"

    monkeypatch.setattr(ado_client.requests, "get", fake_get)
    monkeypatch.setattr(ado_client.time, "sleep", lambda s: None)

    resultado = ado_client._get_con_reintentos("http://x", headers={}, timeout=10, intentos=3, espera=0)

    assert resultado == "respuesta-ok"
    assert llamadas["n"] == 3


def test_se_rinde_despues_de_agotar_los_intentos(monkeypatch):
    def fake_get(url, headers, timeout):
        raise requests.exceptions.ConnectionError("Failed to resolve (simulado)")

    monkeypatch.setattr(ado_client.requests, "get", fake_get)
    monkeypatch.setattr(ado_client.time, "sleep", lambda s: None)

    with pytest.raises(requests.exceptions.ConnectionError):
        ado_client._get_con_reintentos("http://x", headers={}, timeout=10, intentos=3, espera=0)


def test_no_reintenta_errores_http_reales(monkeypatch):
    """Un 401/403/404 no es un problema de red transitorio — no tiene
    sentido reintentar, así que ese tipo de excepción no debe quedar
    atrapada por el retry (requests.get la propaga directo)."""
    def fake_get(url, headers, timeout):
        raise ValueError("esto no es un error de red")

    monkeypatch.setattr(ado_client.requests, "get", fake_get)

    with pytest.raises(ValueError):
        ado_client._get_con_reintentos("http://x", headers={}, timeout=10, intentos=3, espera=0)
