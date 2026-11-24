"""Testes do detector de bloqueio, sem rede.

O caso central: uma página de bloqueio não pode ser confundida com receita
quebrada; caso contrário, o coletor aciona o LLM sem necessidade e pode gravar
lixo na Bronze.
"""

import pytest

from app import bloqueio

# Recorte fiel da resposta real da Amazon à máquina local em 14/07/2026
# (HTTP 503, 1.643 caracteres). Aqui só o essencial para a decisão.
HTML_AMAZON_503 = (
    '<!doctype html><html><head><meta charset="utf-8">'
    "<title>Amazon.com.br Algo deu errado</title></head>"
    '<body><form id="b" action="/s" method="GET" role="search"></form></body></html>'
)

HTML_PAGINA_REAL = "<html><head><title>Mais Vendidos</title></head><body>" + ("<div>produto</div>" * 500) + "</body></html>"


def test_amazon_503_e_bloqueio_nao_receita_quebrada():
    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        bloqueio.conferir("https://www.amazon.com.br/gp/bestsellers/", HTML_AMAZON_503, 503)
    assert "503" in erro.value.motivo


def test_pagina_de_erro_com_status_200_tambem_aborta():
    """Se a fonte devolver a página de aviso com HTTP 200, o tamanho a identifica."""
    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        bloqueio.conferir("https://www.amazon.com.br/gp/bestsellers/", HTML_AMAZON_503, 200)
    assert "curta" in erro.value.motivo


def test_titulo_de_erro_em_pagina_longa_aborta():
    html = '<html><head><title>Desculpe, algo deu errado</title></head><body>' + ("x" * 9000) + "</body></html>"
    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        bloqueio.conferir("https://www.amazon.com.br/gp/bestsellers/", html, 200)
    assert "título" in erro.value.motivo


def test_captcha_tem_precedencia_e_vira_desafio_etico():
    """CAPTCHA é parada ética (451), não indisponibilidade, mesmo em página curta."""
    with pytest.raises(bloqueio.DesafioAntiBot):
        bloqueio.conferir("https://www.mercadolivre.com.br/captcha/wall?go=x", "<html></html>", 200)


def test_anti_bot_do_ml_no_html_e_desafio():
    html = '<link href="https://a.mlstatic.com/suspicious-traffic-frontend/x.css">' + ("x" * 9000)
    with pytest.raises(bloqueio.DesafioAntiBot):
        bloqueio.conferir("https://lista.mercadolivre.com.br/tenis", html, 200)


def test_pagina_real_passa_ilesa():
    assert bloqueio.conferir("https://www.amazon.com.br/gp/bestsellers/", HTML_PAGINA_REAL, 200) is None


def test_titulo_da_pagina_extrai_minusculo():
    assert bloqueio.titulo_da_pagina(HTML_AMAZON_503) == "amazon.com.br algo deu errado"


# ---------------------------------------------------------------------------
# Contrato com o n8n (29/09/2026).
# O coletor do Mercado Livre (workflow 5vSP1WtLKpTTVBn6, versão a011f74b) decide se
# tenta de novo lendo o texto do `detail` que esta API devolve: só repete quando ele
# contém MARCA_5XX. Mudar a frase de `PaginaBloqueada` ou do `detail` em `app/main.py`
# desliga a nova tentativa sem nenhum erro visível; a rodada simplesmente é perdida.
# Por isso a frase é travada aqui, nos dois sentidos: 5xx da fonte casa; qualquer
# outra causa de aborto não casa (senão o coletor repetiria o que não deve).
# ---------------------------------------------------------------------------
MARCA_5XX = "entregou a página (HTTP 5"


@pytest.mark.parametrize("status", [500, 502, 503])
def test_contrato_n8n_5xx_da_fonte_leva_a_marca(status):
    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        bloqueio.conferir("https://www.mercadolivre.com.br/mais-vendidos/", HTML_PAGINA_REAL, status)
    assert MARCA_5XX in str(erro.value)


@pytest.mark.parametrize(
    "html, status, piso",
    [
        (HTML_PAGINA_REAL, 404, None),  # 4xx da fonte: não é indisponibilidade passageira
        (HTML_AMAZON_503, 200, None),  # página curta
        (HTML_PAGINA_REAL, 200, 10**6),  # casca: abaixo do piso de bytes do domínio
        ('<html><head><title>Desculpe, algo deu errado</title></head><body>' + ("x" * 9000) + "</body></html>", 200, None),
    ],
)
def test_contrato_n8n_outras_causas_NAO_levam_a_marca(html, status, piso):
    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        bloqueio.conferir("https://www.mercadolivre.com.br/mais-vendidos/", html, status, piso)
    assert MARCA_5XX not in str(erro.value)


def test_contrato_n8n_volume_abaixo_do_piso_NAO_leva_a_marca():
    """O layout novo de 25/09 abortou por aqui: repetir a requisição não conserta seletor."""
    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        bloqueio.conferir_volume("https://www.mercadolivre.com.br/mais-vendidos/", 0, 157, 0.5)
    assert MARCA_5XX not in str(erro.value)


def test_contrato_n8n_o_detail_da_rota_de_coleta_preserva_a_marca(monkeypatch):
    """O IF do n8n lê o `detail` montado em `app/main.py`, não a exceção crua."""
    from fastapi import HTTPException

    from app import coletor, main

    def falha_500(*_a, **_kw):
        raise bloqueio.PaginaBloqueada("https://www.mercadolivre.com.br/mais-vendidos/", "HTTP 500")

    monkeypatch.setattr(coletor, "coletar", falha_500)
    with pytest.raises(HTTPException) as erro:
        main.coletar(main.PedidoColeta(url="https://www.mercadolivre.com.br/mais-vendidos/"))
    assert erro.value.status_code == 503
    assert MARCA_5XX in erro.value.detail
