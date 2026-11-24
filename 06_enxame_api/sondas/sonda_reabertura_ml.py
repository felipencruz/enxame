"""Sonda de REABERTURA do Mercado Livre — o outro lado do episódio de 23–28/07/2026.

**O que este script mede.** A mesma URL, do mesmo servidor, com a mesma lista de
crachás da sonda de 25/07 (`sonda_ua_ml.py`), agora que a fonte voltou a servir
produto. Ele grava o HTML de cada condição e um `medicoes.json` — o que faltou em
28/07, quando a medição foi feita no terminal e **não foi salva**.

**Por que existe.** Afirmação citável precisa de artefato. O fechamento tem artefato bruto
(`02_Dados/raw/sonda_rotas_ml_20260725/`); a reabertura tinha só a linha do Bronze e
execuções do n8n. Sem este par, os dois lados do episódio mais forte do trabalho não
são citáveis com o mesmo tipo de evidência.

**O que ele NÃO é.** Não é coleta: nada daqui entra no Bronze. A condição "Chrome" é
**contrafactual de medição**, como em 25/07 — serve para saber o que a fonte faz, não
para obter dado sob identidade dissimulada. A coleta de produção segue com o
`EnxameBot`, e a identidade nunca foi tocada.

**A página muda todo dia.** O número de hoje não se recupera amanhã; o que se
preserva aqui é o HTML que produziu o número.

Uso (copiar o arquivo, nunca colar o código como string escapada):
    scp -i ~/.ssh/vps_dashboard sonda_reabertura_ml.py root@VPS:/root/
    ssh ... "docker cp /root/sonda_reabertura_ml.py enxame-api:/srv/enxame-api/"
    ssh ... "docker exec -w /srv/enxame-api enxame-api python sonda_reabertura_ml.py"
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/srv/enxame-api")
from app.agentes import conformidade  # noqa: E402

# A URL do COLETOR (com barra final) — é sobre ela que o episódio inteiro fala.
URL = "https://www.mercadolivre.com.br/mais-vendidos/"
SAIDA = Path("/srv/enxame-api/_sonda_reabertura")
TIMEOUT = 30.0
PAUSA = 2.0

# Mesma lista de 25/07, na mesma ordem, para que a comparação seja de método igual.
CANDIDATOS = [
    ("EnxameBot", "EnxameBot/0.1 (+https://automatize-ai.tech)"),
    ("Enxame_com_contato", "Enxame/0.1 (+https://automatize-ai.tech)"),
    ("Enxame_puro", "Enxame/0.1"),
    ("enxame_minusculo", "enxame"),
    ("vazio", ""),
    ("Chrome_controle", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
]

SINAIS = {
    "precos": r"R\$\s*\d",
    "ids_MLB": r"MLB\d{6,}",
    "andes_carousel": r"andes-carousel",
    "poly_card": r"poly-card",
    "anti_bot": r"captcha|suspicious-traffic|Robot Check",
}

LEIA_ME = {
    "o_que_e": "Medição do que o Mercado Livre serve a cada crachá na rota de mais "
               "vendidos, DEPOIS de a fonte reabrir (28/07/2026).",
    "por_que": "O fechamento (25/07) tem artefato bruto; a reabertura não tinha. "
               "Sem os dois lados, o episódio não é citável com a mesma evidência.",
    "metodo": "Mesmo servidor (VPS do projeto), mesma URL do coletor, mesma lista de "
              "crachás e mesmos regex de 25/07. O Agente 1 (robots.txt) é consultado "
              "antes de cada requisição, COM O CRACHÁ DAQUELA CONDIÇÃO — o robots.txt "
              "é por user-agent, e o veredito de cada uma está em "
              "'robots_por_condicao'. (Até 04/08/2026 o script consultava uma vez, "
              "com o primeiro crachá, e reusava o veredito nas seis condições; esta "
              "frase afirmava mais do que o código fazia. Corrigido no código, não "
              "na frase.)",
    "o_que_prova": "Se o crachá honesto (EnxameBot) recebe produto de novo, a série do "
                   "ML pôde ser retomada SEM tocar na identidade do robô.",
    "o_que_nao_prova": "Não explica POR QUE a fonte fechou nem por que reabriu — não há "
                       "acesso ao lado do servidor. E não mede a rota por categoria, "
                       "proibida pelo robots (nunca tocada).",
    "contrafactual_chrome": "A condição Chrome é medição, não coleta: nada daqui vai "
                            "para o Bronze. Coletar sob esse crachá seria a "
                            "impersonação recusada em 25/07.",
    "perecivel": "A página muda todo dia; os bytes de hoje não se reproduzem amanhã. "
                 "O HTML gravado ao lado é o que sustenta o número.",
}


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"URL: {URL}")

    registros = []
    vereditos = []
    print(f"\n{'condicao':22} {'status':>6} {'bytes':>9} {'MLB':>6} {'R$':>5}  veredito")
    for rotulo, ua in CANDIDATOS:
        # O Agente 1 e consultado POR CRACHA, com o UA que sera enviado.
        # `robots.txt` e por user-agent, e este script existe justamente para
        # variar o user-agent -- o ML da `Disallow: /` para ClaudeBot/GPTBot e
        # `*` para o resto, entao o veredito PODE diferir entre candidatos.
        # Ate 04/08 consultava-se uma vez, com o primeiro UA, e reusava-se nas 6
        # condicoes; e o `_leia_me` gravado no artefato afirmava "consultado antes
        # de qualquer requisicao" -- mais forte do que o codigo fazia.
        #
        # Nao custa 6 downloads do robots: o cache do `conformidade` guarda o
        # PARSER por host e reavalia `can_fetch(ua, url)` a cada chamada.
        veredito = conformidade.verificar(URL, user_agent=ua or conformidade.USER_AGENT_PADRAO)
        vereditos.append({"condicao": rotulo, "permitido": veredito.permitido,
                          "motivo": veredito.motivo, "crawl_delay": veredito.crawl_delay})
        registro = {"condicao": rotulo, "user_agent": ua, "url": URL,
                    "robots": {"permitido": veredito.permitido, "motivo": veredito.motivo,
                               "crawl_delay": veredito.crawl_delay}}
        if not veredito.permitido:
            registro.update(resultado="negado_pelo_robots")
            registros.append(registro)
            print(f"{rotulo:22} {'-':>6} {'-':>9} {'-':>6} {'-':>5}  NEGADO PELO ROBOTS")
            continue

        espera = max(veredito.crawl_delay or 0.0, PAUSA)
        cabecalhos = {"Accept-Language": "pt-BR,pt;q=0.9"}
        if ua:
            cabecalhos["User-Agent"] = ua
        try:
            resposta = httpx.get(URL, headers=cabecalhos, timeout=TIMEOUT, follow_redirects=True)
        except Exception as erro:  # noqa: BLE001
            registro.update(resultado="erro_de_rede", erro=repr(erro))
            registros.append(registro)
            print(f"{rotulo:22} ERRO {erro!r}")
            # A pausa vale TAMBEM aqui: antes, o `continue` pulava o sleep e a
            # proxima replica disparava sem intervalo -- rajada justamente quando a
            # fonte pode estar sob estresse.
            time.sleep(espera)
            continue

        sinais = {nome: len(re.findall(padrao, resposta.text)) for nome, padrao in SINAIS.items()}
        nome_arquivo = f"{carimbo}_ml_mais-vendidos_{rotulo}.html"
        (SAIDA / nome_arquivo).write_bytes(resposta.content)
        registro.update(
            resultado="ok",
            status=resposta.status_code,
            bytes=len(resposta.content),
            url_final=str(resposta.url),
            sinais=sinais,
            html_salvo=nome_arquivo,
        )
        registros.append(registro)
        tem_dado = sinais["ids_MLB"] > 0 and sinais["precos"] > 0
        print(f"{rotulo:22} {resposta.status_code:>6} {len(resposta.content):>9} "
              f"{sinais['ids_MLB']:>6} {sinais['precos']:>5}  "
              f"{'TEM DADO' if tem_dado else 'casca'}")
        time.sleep(espera)

    destino = SAIDA / f"{carimbo}_medicoes.json"
    destino.write_text(
        json.dumps(
            {
                "_leia_me": LEIA_ME,
                "executado_em_utc": datetime.now(timezone.utc).isoformat(),
                "url": URL,
                # Um veredito POR CONDICAO, nao um so reusado: o robots e por
                # user-agent, e o artefato tem de mostrar o que foi perguntado
                # para CADA cracha (04/08).
                "robots_por_condicao": vereditos,
                "condicoes": registros,
                "comparacao_25_07": {
                    "fonte": "02_Dados/raw/sonda_rotas_ml_20260725/",
                    "EnxameBot_bytes": 133957,
                    "EnxameBot_ids_MLB": 0,
                    "EnxameBot_precos": 0,
                    "Chrome_bytes": 443516,
                    "observacao": "valores de 25/07 citados para contraste; a medição "
                                  "desta rodada é a das condições acima",
                },
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nGravado: {destino}")


if __name__ == "__main__":
    main()
