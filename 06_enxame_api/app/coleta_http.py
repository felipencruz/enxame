"""Busca de HTML com identidade transparente (user-agent próprio).

A conformidade com o robots.txt é verificada antes, pelo Agente 1; esta função
só executa o GET. Se o robots.txt declarar crawl-delay, quem chama deve
respeitá-lo entre requisições consecutivas ao mesmo domínio.

Quem aplica a pausa
-------------------
O `crawl_delay` é lido do robots e devolvido na resposta da API, mas a pausa é
aplicada por quem chama. Situação conferida em 04/08/2026:

1. Quem chama é o n8n, que espera 3 s fixos entre vitrines
   (`await new Promise(r => setTimeout(r, 3000))` no Code node do coletor).
2. O que as fontes declaram, medido pelo Agente 1: Amazon, Mercado Livre,
   YouTube e `suggestqueries.google.com` (robots 404) não declaram crawl-delay;
   a Shopee declara 1,0 s.

Portanto não há descumprimento: o único `Crawl-delay` declarado é 1,0 s e o
coletor espera 3 s. A conformidade, porém, vem de uma constante fixa, não do
que a fonte pede; se uma fonte passar a declarar 5 s, o coletor não saberá.

Por isso a resposta da API traz `pausa_recomendada_s`: um número já resolvido
(`max(crawl_delay, PISO)`) que quem chama pode usar direto, em vez de um
`crawl_delay` que costuma ser `None`. Ligar o n8n a esse campo é uma mudança
em produção que ficou fora do escopo da coleta; este módulo garante que o
número existe e está correto.

Antes de devolver o HTML, a resposta passa pelo detector de bloqueio
(`app.bloqueio`): uma fonte que bloqueou o acesso aborta aqui, sem chegar ao
coletor e sem ser confundida com receita quebrada.
"""

import httpx

from app import bloqueio
from app.agentes.conformidade import USER_AGENT_PADRAO

TIMEOUT_SEGUNDOS = 30.0

# Piso de cortesia entre requisições ao mesmo domínio. Os 3,0 s são o mesmo valor
# que o Code node dos coletores do n8n já espera (`setTimeout(r, 3000)`); a
# constante fica aqui para que os dois lados usem o mesmo número, em vez de duas
# cópias que podem divergir. Ver "Quem aplica a pausa" no topo.
PISO_POLITENESS_SEGUNDOS = 3.0


def pausa_recomendada(crawl_delay: float | None) -> float:
    """A pausa que quem chama deve respeitar: o que a fonte pede, nunca menos que o piso."""
    return max(crawl_delay or 0.0, PISO_POLITENESS_SEGUNDOS)


def buscar_html(
    url: str, user_agent: str = USER_AGENT_PADRAO, piso_bytes: int | None = None
) -> str:
    """Busca a página e a submete ao detector de bloqueio antes de devolvê-la.

    `piso_bytes` é a régua de volume do domínio (dado, em `receitas/_volume_esperado.json`).
    Quem passa o número é o coletor, que já leu a expectativa; aqui ele só é
    repassado, pois este módulo não decide política. Omitido, a régua de volume
    não é aplicada.
    """
    resposta = httpx.get(
        url,
        timeout=TIMEOUT_SEGUNDOS,
        follow_redirects=True,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9",
        },
    )
    bloqueio.conferir(str(resposta.url), resposta.text, resposta.status_code, piso_bytes)
    return resposta.text
