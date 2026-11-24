"""Testes do Agente 1 (Conformidade), sem rede: o robots.txt é injetado."""

import httpx
import pytest

from app.agentes import conformidade

ROBOTS_EXEMPLO = """\
User-agent: *
Disallow: /checkout/
Disallow: /carrinho
Crawl-delay: 2

User-agent: BotProibido
Disallow: /
"""


@pytest.fixture(autouse=True)
def _cache_limpo():
    conformidade.limpar_cache()
    yield
    conformidade.limpar_cache()


def _simular_robots(monkeypatch, status_code=200, texto=ROBOTS_EXEMPLO, erro=None):
    def falso_get(url, **kwargs):
        if erro:
            raise erro
        return httpx.Response(status_code, text=texto, request=httpx.Request("GET", url))

    monkeypatch.setattr(conformidade.httpx, "get", falso_get)


def test_url_permitida(monkeypatch):
    _simular_robots(monkeypatch)
    v = conformidade.verificar("https://exemplo.com.br/produto/tenis-123")
    assert v.permitido
    assert v.crawl_delay == 2.0


def test_url_bloqueada_por_disallow(monkeypatch):
    _simular_robots(monkeypatch)
    v = conformidade.verificar("https://exemplo.com.br/checkout/pagamento")
    assert not v.permitido
    assert "Disallow" in v.motivo


def test_user_agent_banido(monkeypatch):
    _simular_robots(monkeypatch)
    v = conformidade.verificar("https://exemplo.com.br/qualquer", user_agent="BotProibido")
    assert not v.permitido


def test_robots_inexistente_permite(monkeypatch):
    _simular_robots(monkeypatch, status_code=404, texto="")
    v = conformidade.verificar("https://exemplo.com.br/produto/1")
    assert v.permitido
    assert "404" in v.motivo


def test_robots_inacessivel_nega_fail_closed(monkeypatch):
    _simular_robots(monkeypatch, erro=httpx.ConnectTimeout("timeout"))
    v = conformidade.verificar("https://exemplo.com.br/produto/1")
    assert not v.permitido
    assert "fail-closed" in v.motivo


def test_erro_servidor_nega_fail_closed(monkeypatch):
    _simular_robots(monkeypatch, status_code=503, texto="")
    v = conformidade.verificar("https://exemplo.com.br/produto/1")
    assert not v.permitido


def test_url_invalida_nega():
    v = conformidade.verificar("ftp://exemplo.com/arquivo")
    assert not v.permitido
    assert "inválida" in v.motivo


# robots.txt real do Mercado Livre (capturado em 13/07/2026, trecho relevante).
# Fixa o comportamento do portão de ética contra o alvo real.
ROBOTS_ML = """\
User-agent: Amazonbot
User-agent: ClaudeBot
User-agent: GPTBot
Disallow: /

User-agent: *
Disallow: /gz/checkout/
Disallow: /mais-vendidos/MLB
Disallow: /ofertas?
Allow: /home/recommendations/pom
"""


def test_ml_mais_vendidos_geral_permitido(monkeypatch):
    _simular_robots(monkeypatch, texto=ROBOTS_ML)
    v = conformidade.verificar("https://www.mercadolivre.com.br/mais-vendidos/")
    assert v.permitido  # a página agregada é a única porta de oferta que usamos


def test_ml_mais_vendidos_por_categoria_bloqueado(monkeypatch):
    # Disallow: /mais-vendidos/MLB: as páginas por categoria são proibidas no robots
    _simular_robots(monkeypatch, texto=ROBOTS_ML)
    v = conformidade.verificar("https://www.mercadolivre.com.br/mais-vendidos/MLB1051")
    assert not v.permitido


def test_ml_bots_de_ia_nomeados_bloqueados_em_tudo(monkeypatch):
    # O ML dá Disallow: / para ClaudeBot, GPTBot e Amazonbot; por isso o projeto usa EnxameBot
    _simular_robots(monkeypatch, texto=ROBOTS_ML)
    v = conformidade.verificar("https://www.mercadolivre.com.br/mais-vendidos/", user_agent="ClaudeBot")
    assert not v.permitido


# --- A identidade do robô (desde 15/07/2026) ---------------------------------
# A documentação do projeto afirma que o robô se identifica com um canal de contato.
# Estes testes garantem que o user-agent de produção cumpre esse compromisso ético.

def test_user_agent_declara_quem_somos_e_como_contatar():
    ua = conformidade.USER_AGENT_PADRAO
    assert ua.startswith("EnxameBot/"), "precisa nomear o robô e a versão"
    assert "+" in ua and "http" in ua, "precisa trazer um canal de contato (convenção de crawler)"


def test_user_agent_nao_finge_ser_navegador():
    """Limite do projeto: identidade transparente, nunca disfarce de navegador."""
    ua = conformidade.USER_AGENT_PADRAO.lower()
    for disfarce in ("mozilla", "chrome", "safari", "webkit", "gecko"):
        assert disfarce not in ua


def test_user_agent_mantem_o_token_bot_de_proposito():
    """A Amazon omite o preço para quem se declara robô. O token 'Bot' é mantido mesmo
    assim (decisão do projeto, 15/07); este teste falha se ele for removido."""
    assert "bot" in conformidade.USER_AGENT_PADRAO.lower()


def test_o_contato_no_ua_nao_muda_o_veredito_do_robots(monkeypatch):
    """O RobotFileParser casa por useragent.split('/')[0], isto é, 'EnxameBot'. O sufixo de
    contato não pode alterar a decisão de conformidade."""
    _simular_robots(monkeypatch, texto=ROBOTS_ML)
    url = "https://www.mercadolivre.com.br/mais-vendidos/"
    v_completo = conformidade.verificar(url, user_agent=conformidade.USER_AGENT_PADRAO)
    conformidade.limpar_cache()
    _simular_robots(monkeypatch, texto=ROBOTS_ML)
    v_curto = conformidade.verificar(url, user_agent="EnxameBot")
    assert v_completo.permitido == v_curto.permitido is True

    conformidade.limpar_cache()
    _simular_robots(monkeypatch, texto=ROBOTS_ML)
    proibida = "https://www.mercadolivre.com.br/mais-vendidos/MLB1051"
    assert conformidade.verificar(proibida, user_agent=conformidade.USER_AGENT_PADRAO).permitido is False
