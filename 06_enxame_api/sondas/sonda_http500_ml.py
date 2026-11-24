"""Por que o coletor do Mercado Livre recebe HTTP 500 e a sonda de reabertura recebe 200?

Pergunta de 29/09/2026. Desde 28/09 18:00 BRT (21:00 UTC) as 5 rodadas do coletor
terminam com "A fonte não entregou a página (HTTP 500)". Às 22:03 UTC de 29/09 a
`sonda_reabertura_ml.py`, do mesmo container e na mesma URL, recebeu **200 com 388
`MLB`** para o crachá `EnxameBot`. As duas usam `httpx.get` com o mesmo User-Agent;
a diferença visível no código é o cabeçalho `Accept`, que só o `coleta_http` envia.

Este script isola essa variável, uma requisição por condição, com a pausa de
produção entre elas (`PISO_POLITENESS_SEGUNDOS`):

  (a) o caminho de PRODUÇÃO, literal: `coleta_http.buscar_html(URL)` — sem piso de
      bytes, para ver o status cru em vez da exceção da régua;
  (b) os cabeçalhos de produção, chamados à mão (status e bytes visíveis);
  (c) os mesmos, SEM o `Accept`  — é o que a sonda de reabertura manda;
  (d) os mesmos, com `Accept: */*`.

Não é coleta: nada entra no Bronze, não aciona LLM, e o crachá é sempre o de
produção (`EnxameBot`). O Agente 1 (robots) é consultado antes.

Uso (copiar o arquivo, nunca colar o código como string escapada):
    scp -i ~/.ssh/vps_dashboard sonda_http500_ml.py root@VPS:/root/
    ssh ... "docker cp /root/sonda_http500_ml.py enxame-api:/srv/enxame-api/"
    ssh ... "docker exec -w /srv/enxame-api enxame-api python sonda_http500_ml.py"
"""

from __future__ import annotations

import re
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/srv/enxame-api")
from app import coleta_http  # noqa: E402
from app.agentes import conformidade  # noqa: E402

URL = "https://www.mercadolivre.com.br/mais-vendidos/"
UA = conformidade.USER_AGENT_PADRAO
BASE = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}

CONDICOES = [
    ("b_producao_a_mao", {**BASE, "Accept": "text/html,application/xhtml+xml"}),
    ("c_sem_accept", dict(BASE)),
    ("d_accept_tudo", {**BASE, "Accept": "*/*"}),
]


def resumo(texto: str) -> str:
    return f"MLB={len(re.findall(r'MLB[0-9]{6,}', texto))}"


def main() -> None:
    veredito = conformidade.verificar(URL, user_agent=UA)
    print(f"robots: permitido={veredito.permitido} ({veredito.motivo})")
    if not veredito.permitido:
        return
    pausa = coleta_http.pausa_recomendada(veredito.crawl_delay)

    try:
        html = coleta_http.buscar_html(URL)
        print(f"a_buscar_html_producao  OK   bytes={len(html.encode())} {resumo(html)}")
    except Exception as erro:  # noqa: BLE001
        print(f"a_buscar_html_producao  EXCECAO {type(erro).__name__}: {erro}")
    time.sleep(pausa)

    for rotulo, cab in CONDICOES:
        try:
            r = httpx.get(URL, headers=cab, timeout=coleta_http.TIMEOUT_SEGUNDOS,
                          follow_redirects=True)
            print(f"{rotulo:24} {r.status_code}  bytes={len(r.content)} {resumo(r.text)}"
                  f"  final={r.url}")
        except Exception as erro:  # noqa: BLE001
            print(f"{rotulo:24} ERRO {erro!r}")
        time.sleep(pausa)


if __name__ == "__main__":
    main()
