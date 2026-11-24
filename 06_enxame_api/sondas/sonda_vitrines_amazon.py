"""Sonda de diagnóstico das vitrines da Amazon — read-only, sem LLM, sem gravação.

POR QUE ELA EXISTE (05/08/2026)
-------------------------------
Na rodada das 12:00 BRT de 05/08, **5 das 22 vitrines** gravaram linha de erro em vez
de 50 produtos (855 linhas no lugar de 1.100). O motivo gravado no Bronze é
`[ERRO] Request failed with status code 503` — e **só isso**: o n8n registra o status
code, **não o corpo da resposta**.

**E é aí que está o problema que esta sonda resolve.** O método manda distinguir
*"503 COM 'volume' no motivo é a régua nova; 503 sem 'volume' é a fonte"* — **mas essa
distinção não existe na linha gravada**, porque o motivo detalhado fica no corpo, que o
Bronze não guarda. Sem medir de novo, os dois casos são indistinguíveis: um é a Amazon
recusando, o outro seria a nossa régua reprovando página boa.

O QUE ELA FAZ: para cada vitrine passada, busca a página com o crachá honesto, passando
pelo Agente 1, e reporta **qual das camadas decidiria** — HTTP da fonte, piso de bytes,
ou piso de itens. Uma requisição por vitrine.

DOIS DEFEITOS CONSERTADOS EM 11/08/2026 — os dois faziam a sonda responder com
confiança à pergunta errada, que é pior do que não responder:

1. **O `SLUGS_PADRAO` era uma lista fixa** com as 5 vitrines que falharam em
   ~~05/08 (`amazon-devices, automotive, kitchen, videogames, furniture`)~~, usada
   quando ninguém passava argumento. **As vitrines que falham mudam a cada rodada**,
   então rodá-la sem argumento em qualquer outro dia media vitrines saudáveis e
   devolvia cinco `ok` — sustentando um "está tudo bem" sobre vitrines que não
   falharam. **Hoje ela EXIGE os slugs e falha alto sem eles.** *Para descobrir os
   slugs do dia sem adivinhar, rode na máquina local, fora do container:*
   `python 03_Analise/vitrines_amazon_em_erro.py`

2. **A classificação estava invertida no caso que mais importa.** O código dizia
   ~~"PARADA TECNICA (a NOSSA regua)"~~ para toda `PaginaBloqueada` — mas essa exceção
   é levantada por `bloqueio.conferir()` **também para todo HTTP >= 400**, e a própria
   classe se documenta como *"a fonte não entregou a página real"*. Ou seja: uma vitrine
   respondendo 503 **no instante da sondagem** seria reportada como culpa da NOSSA régua,
   que é exatamente o contrário do que esta sonda existe para decidir. *Só não mordeu
   ainda porque nas duas execuções reais (05 e 10/08) as vitrines voltaram saudáveis.*
   **Hoje o motivo é lido: `HTTP nnn` é a fonte; piso de bytes e página curta são a régua.**

**O QUE A EXECUÇÃO REAL DE 11/08 DESMENTIU, e vale mais que os dois consertos:** o
primeiro rascunho deste conserto avisava ~~"HTTP 404 → slug inexistente?"~~. **A Amazon
não devolve 404 para slug inventado** — ela serve página genérica com **200**, e a parada
cai no **piso de itens** (`0 itens`), que é a mensagem da NOSSA régua. *Suposição escrita
como pista vira pista errada; a pista certa mora no ramo do piso de itens, e foi medida.*

Uso, de dentro do container:
    docker exec -w /srv/enxame-api enxame-api python sonda_vitrines_amazon.py sports hi furniture
"""

import sys

from app import bloqueio, coleta_http, coletor
from app.agentes import analista_estrutura as ae
from app.agentes import conformidade

DOMINIO = "www.amazon.com.br"
BASE = "https://www.amazon.com.br/gp/bestsellers/{}/"
UA = conformidade.USER_AGENT_PADRAO

USO = """uso: python sonda_vitrines_amazon.py <slug> [<slug> ...]

Esta sonda NAO tem lista padrao, de proposito: as vitrines que falham mudam a cada
rodada, e uma lista fixa mede as vitrines erradas devolvendo 'ok' com confianca.

Para descobrir os slugs da ultima rodada com falha, rode na maquina local:
    python 03_Analise/vitrines_amazon_em_erro.py

Exemplo: python sonda_vitrines_amazon.py sports hi furniture"""


def sondar(slug: str) -> None:
    url = BASE.format(slug)
    regra = bloqueio.volume_esperado(DOMINIO) or {}
    piso_b = regra.get("piso_bytes")
    esperado = regra.get("itens_esperados")

    veredito = conformidade.verificar(url, UA)
    if not veredito.permitido:
        print(f"{slug:<16} AGENTE 1 NEGOU: {veredito.motivo}")
        return

    try:
        html = coleta_http.buscar_html(url, UA, piso_bytes=piso_b)
    except bloqueio.DesafioAntiBot as erro:
        print(f"{slug:<16} FALHA, A FONTE SERVIU DESAFIO ANTI-BOT: {erro}")
        return
    except bloqueio.PaginaBloqueada as erro:
        # `conferir()` levanta esta mesma excecao para HTTP >= 400 (a FONTE recusou) e
        # para os pisos de tamanho (a NOSSA regua). Quem separa e o motivo, nao a classe.
        if erro.motivo.startswith("HTTP "):
            print(f"{slug:<16} FALHA, A FONTE RECUSOU: {erro.motivo}")
        else:
            print(f"{slug:<16} FALHA, PARADA TECNICA (a regua do projeto): {erro.motivo}")
        return
    except Exception as erro:  # rede, timeout, DNS — nem fonte nem regua
        print(f"{slug:<16} FALHA DE TRANSPORTE: {type(erro).__name__}: {str(erro)[:120]}")
        return

    receita = coletor.carregar_receita_mais_recente(DOMINIO)
    linhas = ae.aplicar_receita(html, receita)
    try:
        bloqueio.conferir_volume(url, len(linhas), esperado, regra.get("piso_fracao", 0.5))
    except bloqueio.PaginaBloqueada as erro:
        # 0 itens numa página que VEIO tem dois pais: receita quebrada ou slug errado.
        # Medido em 11/08: slug inexistente na Amazon **não dá 404** — ela serve página
        # genérica com 200, e a parada cai aqui. Sem esta linha, um erro de digitação
        # seria lido como "a régua reprovou uma vitrine boa".
        pista = " (0 itens também é o sintoma de slug inexistente)" if not linhas else ""
        print(f"{slug:<16} FALHA, PISO DE ITENS REPROVOU: {len(linhas)} itens — {erro.motivo}{pista}")
        return
    print(f"{slug:<16} ok — {len(html):,} bytes · {len(linhas)} itens")


if __name__ == "__main__":
    alvos = sys.argv[1:]
    if not alvos:
        print(USO)
        raise SystemExit(2)
    print(f"crachá: {UA}\n")
    for slug in alvos:
        sondar(slug)
