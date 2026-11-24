"""Sonda: alguma rota do Mercado Livre ainda serve DADO ao cracha honesto?

CONTEXTO (25/07/2026). O coletor do ML esta parado desde 23/07 15:00 UTC. Medido:
a rota /mais-vendidos/ servida ao EnxameBot devolve 134 KB SEM PRODUTO NENHUM --
zero precos, zero IDs MLB, zero carrossel, e sem captcha. Ao Chrome a mesma URL
devolve 443 KB com 408 IDs e 257 precos. Nao e a receita: o servidor nao manda o
dado. Nenhum seletor conserta isso, e por isso NAO se aciona o Agente 4 aqui.

O QUE ESTA SONDA FAZ. Percorre rotas candidatas do ML, passando cada uma pelo
Agente 1 (robots.txt) ANTES de requisitar, e mede com o cracha honesto se ainda
existe dado no HTML. E o padrao de decisao que o projeto ja usa desde 16/07: "a
fonte escolhe a tecnica por nos" -- onde ela fecha, procura-se a porta que ela
deixou aberta, sem nunca mentir sobre quem somos.

O QUE ELA NAO FAZ, de proposito: nao testa remocao do token "Bot". Essa decisao
foi tomada e registrada em 15/07 e reafirmada duas vezes; nao esta em jogo.

Uso (copiar o arquivo, nunca colar o codigo como string escapada):
    docker cp sonda_rotas_ml.py enxame-api:/srv/enxame-api/
    docker exec -w /srv/enxame-api enxame-api python sonda_rotas_ml.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, "/srv/enxame-api")
from app.agentes import conformidade  # noqa: E402

SAIDA = Path("/srv/enxame-api/_sonda_ml")
PISO_DELAY = 1.5
TIMEOUT = 30.0
HONESTO = conformidade.USER_AGENT_PADRAO

CANDIDATAS = [
    ("mais-vendidos (rota atual, quebrada)", "https://www.mercadolivre.com.br/mais-vendidos/"),
    ("ofertas do dia", "https://www.mercadolivre.com.br/ofertas"),
    ("lista: tenis-corrida (receita antiga)", "https://lista.mercadolivre.com.br/tenis-corrida"),
    ("lista: fone-de-ouvido", "https://lista.mercadolivre.com.br/fone-de-ouvido"),
    ("mais-vendidos celulares (MLB1051)", "https://www.mercadolivre.com.br/mais-vendidos/MLB1051"),
    ("home", "https://www.mercadolivre.com.br/"),
]

SINAIS = {
    "precos": r"R\$\s*\d",
    "ids_MLB": r"MLB\d{6,}",
    "andes_carousel": r"andes-carousel",
    "poly_card": r"poly-card",
    "ui_search_result": r"ui-search-result",
    "anti_bot": r"captcha|suspicious-traffic|Robot Check",
}


def sondar(rotulo: str, url: str) -> dict:
    veredito = conformidade.verificar(url, user_agent=HONESTO)
    registro = {
        "rotulo": rotulo,
        "url": url,
        "robots_permitido": veredito.permitido,
        "robots_motivo": veredito.motivo,
        "crawl_delay": veredito.crawl_delay,
    }
    if not veredito.permitido:
        registro["resultado"] = "negado_pelo_robots"
        return registro

    espera = max(veredito.crawl_delay or 0.0, PISO_DELAY)
    try:
        resposta = httpx.get(
            url,
            headers={"User-Agent": HONESTO, "Accept-Language": "pt-BR,pt;q=0.9"},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
    except Exception as erro:
        # A pausa vale TAMBEM aqui: a requisicao saiu, so nao voltou. Antes,
        # este `return` pulava o `time.sleep` do fim e a rota seguinte era
        # sondada sem intervalo.
        registro.update(resultado="erro_de_rede", erro=repr(erro))
        time.sleep(espera)
        return registro

    texto = resposta.text
    registro.update(
        resultado="ok",
        status=resposta.status_code,
        bytes=len(resposta.content),
        url_final=str(resposta.url),
        sinais={nome: len(re.findall(pat, texto)) for nome, pat in SINAIS.items()},
    )
    registro["_html"] = resposta.content
    time.sleep(espera)
    return registro


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    registros = []

    for rotulo, url in CANDIDATAS:
        r = sondar(rotulo, url)
        html = r.pop("_html", None)
        if html:
            nome = f"{carimbo}_ml_{re.sub(r'[^a-z0-9]+', '-', rotulo.lower())[:40]}.html"
            (SAIDA / nome).write_bytes(html)
            r["html_salvo"] = nome
        registros.append(r)

        if r["resultado"] == "negado_pelo_robots":
            print(f"  [ROBOTS NEGOU] {rotulo}")
            continue
        if r["resultado"] != "ok":
            print(f"  [{r['resultado']}] {rotulo}")
            continue
        s = r["sinais"]
        veredito = "TEM DADO" if s["ids_MLB"] > 0 and s["precos"] > 0 else "casca (sem dado)"
        print(
            f"  [{r['status']}] {rotulo:42} {r['bytes']:>8} B  "
            f"MLB={s['ids_MLB']:>4} R$={s['precos']:>4} antibot={s['anti_bot']:>2}  -> {veredito}"
        )

    destino = SAIDA / f"{carimbo}_sonda_ml.json"
    destino.write_text(
        json.dumps(
            {"executado_em_utc": datetime.now(timezone.utc).isoformat(),
             "user_agent": HONESTO, "rotas": registros},
            ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    print(f"\nGravado: {destino}")


if __name__ == "__main__":
    main()
