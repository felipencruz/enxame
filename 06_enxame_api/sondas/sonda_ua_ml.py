"""Tirar o token "Bot" do User-Agent faria o Mercado Livre voltar a servir dado?

Pergunta de 25/07/2026, que precisa de MEDICAO antes de virar decisao de etica:
se nao funcionar, nao ha dilema a discutir.

Ja se sabe (medido em 25/07): EnxameBot -> 134 KB sem produto; Chrome -> 443 KB com
408 IDs; UA padrao do n8n (que NAO contem "Bot") -> 134 KB sem produto. Esse
ultimo ja sugere que o portao e "parece navegador?", nao "diz Bot?". Este script
testa a hipotese diretamente, na mesma URL, do mesmo VPS, em sequencia.

ARQUIVO RESTAURADO EM 29/07/2026.
O original vivia so dentro do container `enxame-api` (nunca foi versionado), e o
`docker compose up --build` do deploy do registro de custo recriou o container,
levando junto este e outros scripts de metodo. Esta copia foi remontada a partir
de uma leitura integral feita horas antes. O conteudo confere com o que foi lido;
nao da para garantir se havia algo depois da linha 60, ate onde a leitura chegou
(o arquivo terminava, aparentemente, no `time.sleep` do fim do laco).

Artefato que mora so no servidor nao esta versionado, esta hospedado. Por isso
`sondas/` existe.
"""

import re
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/srv/enxame-api")
from app.agentes import conformidade  # noqa: E402

URL = "https://www.mercadolivre.com.br/mais-vendidos"

CANDIDATOS = [
    ("EnxameBot (atual, honesto)", "EnxameBot/0.1 (+https://automatize-ai.tech)"),
    ("Enxame + contato (a proposta)", "Enxame/0.1 (+https://automatize-ai.tech)"),
    ("Enxame puro", "Enxame/0.1"),
    ("enxame minusculo", "enxame"),
    ("vazio", ""),
    ("Chrome (controle)", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
]

# Piso de cortesia: nunca requisitar mais rapido que isto, mesmo se o robots
# nao declarar `Crawl-delay`.
PISO_DELAY = 2.0

print(f"URL: {URL}")
print(f"\n{'condicao':32} {'status':>6} {'bytes':>9} {'IDs MLB':>8} {'R$':>6}  veredito")

for rotulo, ua in CANDIDATOS:
    # O Agente 1 e consultado POR CANDIDATO, com o UA que sera de fato enviado.
    # `robots.txt` e por user-agent -- e o proposito deste script e justamente
    # variar o user-agent. Consultar uma vez e reusar o veredito nas 6 condicoes
    # perguntaria por um cracha e requisitaria com outro (04/08).
    #
    # Consultar 6 vezes NAO gera 6 downloads: o cache do `conformidade` guarda o
    # PARSER por host e reavalia `can_fetch(ua, url)` a cada chamada -- conferido
    # no codigo em 04/08. O portao fica correto de graca.
    veredito = conformidade.verificar(URL, user_agent=ua or conformidade.USER_AGENT_PADRAO)

    # E o veredito BARRA, nao so informa. Ate 04/08 este script imprimia o
    # resultado do Agente 1 e requisitava de qualquer forma -- portao de etica sem
    # portao, no arquivo que existe para medir uma decisao de etica. As outras tres
    # sondas ja barravam.
    if not veredito.permitido:
        print(f"{rotulo:32} {'-':>6} {'-':>9} {'-':>8} {'-':>6}  NEGADO PELO ROBOTS: {veredito.motivo}")
        continue

    espera = max(veredito.crawl_delay or 0.0, PISO_DELAY)
    cabecalhos = {"Accept-Language": "pt-BR,pt;q=0.9"}
    if ua:
        cabecalhos["User-Agent"] = ua
    try:
        r = httpx.get(URL, headers=cabecalhos, timeout=30.0, follow_redirects=True)
        ids = len(re.findall(r"MLB\d{6,}", r.text))
        precos = len(re.findall(r"R\$\s*\d", r.text))
        marca = "TEM DADO" if ids > 0 and precos > 0 else "casca"
        print(f"{rotulo:32} {r.status_code:>6} {len(r.content):>9} {ids:>8} {precos:>6}  {marca}")
    except Exception as erro:
        print(f"{rotulo:32} ERRO {erro!r}")
    finally:
        # A pausa no `finally`: ela vale TAMBEM no caminho de erro de rede.
        # Antes, o `continue` do `except` pulava o sleep -- e a rajada acontecia
        # exatamente quando a fonte podia estar sob estresse.
        time.sleep(espera)
