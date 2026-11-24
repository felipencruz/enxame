"""Testes da detecção de anti-bot, sem abrir navegador de verdade.

Exercitamos a lógica de decisão (o que conta como desafio) sem subir o
Chromium: isso é responsabilidade de integração, não de teste unitário.
"""

import pytest

from app.coleta_navegador import DesafioAntiBot, MARCADORES_DESAFIO


def _eh_desafio(url_final: str, html: str) -> bool:
    return any(m in url_final.lower() or m in html.lower() for m in MARCADORES_DESAFIO)


def test_captcha_wall_e_desafio():
    assert _eh_desafio("https://www.mercadolivre.com.br/captcha/wall?go_url=x", "<html></html>")


def test_pagina_anti_bot_no_html_e_desafio():
    html = '<link href="https://.../suspicious-traffic-frontend/x.css">'
    assert _eh_desafio("https://lista.mercadolivre.com.br/tenis", html)


def test_pagina_normal_nao_e_desafio():
    html = '<ul class="ui-search-results"><li class="poly-card">produto</li></ul>'
    assert not _eh_desafio("https://lista.mercadolivre.com.br/tenis", html)


def test_excecao_carrega_url_final():
    exc = DesafioAntiBot("https://www.mercadolivre.com.br/captcha/wall")
    assert exc.url_final.endswith("/captcha/wall")
    assert "anti-bot" in str(exc).lower() or "captcha" in str(exc).lower()


# --- O Playwright é carregado só na hora de usar (15/07/2026) -----------------
#
# Medido: 136 MB dos 207 MB de site-packages da imagem de produção eram Playwright,
# carregados por uma linha de `import` no topo do módulo, para um motor que a imagem
# não executa (o Chromium não está nela).

def test_o_modulo_importa_sem_o_playwright(monkeypatch):
    """`app.coleta_navegador` (e portanto o `coletor` e o `main`) tem de subir mesmo
    sem o Playwright instalado; caso contrário, a produção volta a depender do Playwright."""
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    modulo = importlib.reload(importlib.import_module("app.coleta_navegador"))
    assert modulo.MARCADORES_DESAFIO  # o módulo subiu e está utilizável


def test_erro_claro_quando_o_motor_navegador_nao_esta_disponivel(monkeypatch):
    """Se motor='navegador' for pedido em produção, a mensagem tem de explicar o que
    houve, e não ser um ModuleNotFoundError cru no log do n8n."""
    import sys

    from app import coleta_navegador

    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(RuntimeError, match="Motor 'navegador' indisponível"):
        coleta_navegador._carregar_playwright()


def test_playwright_disponivel_em_desenvolvimento():
    """O caso oposto: onde o Playwright está instalado, o carregador devolve a função."""
    from app import coleta_navegador

    assert callable(coleta_navegador._carregar_playwright())
