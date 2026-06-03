"""validate_webhook_url: exige https e bloqueia destinos internos (anti-SSRF)."""

import pytest
from fastapi import HTTPException

from app.routers.teams import validate_webhook_url


def test_https_publico_aceito():
    url = "https://contoso.webhook.office.com/webhookb2/abc/IncomingWebhook/xyz"
    assert validate_webhook_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://contoso.webhook.office.com/x",  # http
        "ftp://exemplo.com/x",                   # esquema invalido
        "https://localhost/x",                   # loopback por nome
        "https://127.0.0.1/x",                   # loopback por IP
        "https://10.0.0.5/x",                    # rede privada
        "https://192.168.1.10/x",                # rede privada
        "https://169.254.169.254/latest",        # link-local (metadata)
        "",                                       # vazio
        None,                                     # None
    ],
)
def test_destinos_rejeitados(url):
    with pytest.raises(HTTPException) as exc:
        validate_webhook_url(url)
    assert exc.value.status_code == 400
