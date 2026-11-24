"""Agente 1: Conformidade (portão de ética da extração).

Antes de qualquer coleta, este agente lê o robots.txt do domínio-alvo e
decide se a URL pode ser acessada pelo nosso user-agent. É determinístico
(sem LLM): a decisão vem do protocolo robots.txt, não de um modelo.

Política fail-closed: se o robots.txt não puder ser lido por erro de
rede ou servidor (timeout, 5xx), a resposta é negar; na dúvida, não coleta.
Exceção padrão do protocolo: robots.txt inexistente (404) significa que o
site não impõe restrições, então a coleta é permitida.
"""

import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

# Identidade transparente do robô. A convenção de crawler (e a politeness vista na
# disciplina 10) pede que o robô declare quem é e como ser contatado, para que o
# dono do site possa nos encontrar. Formato "Nome/versão (+contato)", como
# Googlebot e Bingbot.
#
# URL em vez de e-mail: cumpre a convenção sem expor e-mail pessoal nos logs de
# terceiros (decisão do projeto, 15/07/2026).
#
# O token "Bot" é mantido mesmo com custo em dados: a Amazon serve página sem preço
# a quem se declara robô (experimento controlado em 15/07), e optamos por aceitar
# essa perda em vez de omitir a identidade. Ver o capítulo de ética.
#
# Compatível com o robots.txt: o RobotFileParser casa por `useragent.split("/")[0]`,
# ou seja, "EnxameBot", com o mesmo veredito (coberto por teste).
USER_AGENT_PADRAO = "EnxameBot/0.1 (+https://automatize-ai.tech)"
TIMEOUT_SEGUNDOS = 10.0
CACHE_TTL_SEGUNDOS = 15 * 60  # robots.txt muda raramente; 15 min evita requisições repetidas


@dataclass
class Veredito:
    permitido: bool
    motivo: str
    robots_url: str
    crawl_delay: float | None = None


class _EntradaCache:
    def __init__(self, parser: RobotFileParser | None, status: str):
        self.parser = parser
        self.status = status  # "ok" | "inexistente" | "inacessivel"
        self.criado_em = time.monotonic()

    def expirado(self) -> bool:
        return time.monotonic() - self.criado_em > CACHE_TTL_SEGUNDOS


_cache: dict[str, _EntradaCache] = {}


def _buscar_robots(base: str, robots_url: str) -> _EntradaCache:
    entrada = _cache.get(base)
    if entrada and not entrada.expirado():
        return entrada
    try:
        resposta = httpx.get(
            robots_url,
            timeout=TIMEOUT_SEGUNDOS,
            headers={"User-Agent": USER_AGENT_PADRAO},
            follow_redirects=True,
        )
    except httpx.HTTPError:
        entrada = _EntradaCache(None, "inacessivel")
    else:
        if resposta.status_code == 404:
            entrada = _EntradaCache(None, "inexistente")
        elif resposta.status_code >= 400:
            entrada = _EntradaCache(None, "inacessivel")
        else:
            parser = RobotFileParser()
            parser.parse(resposta.text.splitlines())
            entrada = _EntradaCache(parser, "ok")
    _cache[base] = entrada
    return entrada


def verificar(url: str, user_agent: str = USER_AGENT_PADRAO) -> Veredito:
    """Decide se `url` pode ser coletada pelo `user_agent`, segundo o robots.txt."""
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return Veredito(False, f"URL inválida: {url!r}", robots_url="")

    base = f"{partes.scheme}://{partes.netloc}"
    robots_url = f"{base}/robots.txt"
    entrada = _buscar_robots(base, robots_url)

    if entrada.status == "inacessivel":
        return Veredito(
            False,
            "robots.txt inacessível (erro de rede/servidor), política fail-closed nega a coleta",
            robots_url,
        )
    if entrada.status == "inexistente":
        return Veredito(True, "robots.txt não existe (404), sem restrições declaradas", robots_url)

    assert entrada.parser is not None
    permitido = entrada.parser.can_fetch(user_agent, url)
    delay = entrada.parser.crawl_delay(user_agent)
    if permitido:
        motivo = f"permitido pelo robots.txt para o user-agent {user_agent!r}"
    else:
        motivo = f"bloqueado por regra Disallow do robots.txt para o user-agent {user_agent!r}"
    return Veredito(permitido, motivo, robots_url, crawl_delay=float(delay) if delay else None)


def limpar_cache() -> None:
    """Usado nos testes para isolar cenários."""
    _cache.clear()
