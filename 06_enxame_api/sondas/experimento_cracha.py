"""Experimento do custo da transparencia -- RE-EXECUCAO COM PROVA GRAVADA.

POR QUE EXISTE. Este experimento foi medido pela primeira vez em 15-16/07/2026,
mas a materia-prima nao foi salva: o unico registro era uma anotacao, e nao um
artefato conferivel. Em 25/07/2026 era a unica afirmacao do artigo sem artefato
(as demais tem script auditor ou JSON versionado).

Este script re-executa o experimento gravando TUDO -- HTML bruto de cada
condicao + um JSON com as medicoes -- em 02_Dados/raw/experimento_cracha/.

DESENHO. Para cada rota, a mesma URL e requisitada com identidades diferentes,
3 replicas cada, e mede-se o que o servidor entrega: status, bytes, itens
(pelo seletor da receita VIVA do dominio) e precos (ocorrencias de "R$").
A unica variavel entre condicoes de uma rota e o User-Agent.

AS IDENTIDADES, e o que cada uma testa:
  EnxameBot     identidade honesta de producao -- declara robo e contato
  Enxame        o MESMO cracha sem o token "Bot" -- isola a declaracao de robo
                como unica variavel. NAO e um navegador (precisao de 24/07).
  Chrome        User-Agent de navegador convencional
  Googlebot     finge ser o robo do Google -- e a condicao que produziu o achado
                "a fonte barra quem finge ser um terceiro conhecido"
  EnxameCrawler token diferente, para testar se a fonte barra por token

PORTAO DE ETICA. Toda requisicao passa antes pelo Agente 1 (conformidade), que
le o robots.txt para AQUELE user-agent e nega rota proibida. Rota negada e
registrada como "negado_pelo_robots" e NAO e requisitada. O crawl_delay
declarado por cada fonte e respeitado, com piso de 1,5 s.

LIMITE CONHECIDO. A URL exata da Shopee usada em julho nao foi registrada em
lugar nenhum, entao ela nao e reproduzivel ao pe da letra. O script usa a
primeira rota permitida que responda 200 ao cracha honesto e GRAVA qual foi --
a comparacao entre identidades na MESMA url e o que o artigo afirma, e essa
continua valida.

Uso, de dentro do container (copiar o arquivo, nunca colar o codigo como string escapada):
    docker cp experimento_cracha.py enxame-api:/srv/enxame-api/
    docker exec -w /srv/enxame-api enxame-api python experimento_cracha.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, "/srv/enxame-api")
from app.agentes import conformidade  # noqa: E402

SAIDA = Path("/srv/enxame-api/_experimento_cracha")
RECEITAS = Path("/srv/enxame-api/receitas")
REPLICAS = 3
PISO_DELAY = 1.5
TIMEOUT = 30.0

HONESTO = conformidade.USER_AGENT_PADRAO
IDENTIDADES = {
    "EnxameBot": HONESTO,
    "Enxame": HONESTO.replace("EnxameBot", "Enxame"),
    "EnxameCrawler": HONESTO.replace("EnxameBot", "EnxameCrawler"),
    "Chrome": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Googlebot": "Googlebot/2.1 (+http://www.google.com/bot.html)",
}

# (fonte, rota, url, identidades a comparar)
CONDICOES = [
    ("amazon", "geral", "https://www.amazon.com.br/gp/bestsellers/", ["EnxameBot", "Enxame"]),
    ("amazon", "toys", "https://www.amazon.com.br/gp/bestsellers/toys/", ["EnxameBot", "Enxame"]),
    ("amazon", "sports", "https://www.amazon.com.br/gp/bestsellers/sports/", ["EnxameBot", "Enxame"]),
    (
        "mercadolivre",
        "mais-vendidos",
        "https://www.mercadolivre.com.br/mais-vendidos/",
        ["EnxameBot", "Chrome", "EnxameCrawler"],
    ),
]

# A Shopee entra por descoberta: a url de julho nao foi registrada.
CANDIDATAS_SHOPEE = [
    "https://shopee.com.br/",
    "https://shopee.com.br/Celulares-e-Dispositivos-cat.11036030",
]
IDENTIDADES_SHOPEE = ["EnxameBot", "Chrome", "Googlebot"]

PADRAO_PRECO = re.compile(r"R\$\s*\d")


def seletor_vivo(dominio: str) -> str | None:
    """Le o seletor_item da receita mais recente e APROVADA do dominio."""
    pasta = RECEITAS / dominio
    if not pasta.is_dir():
        return None
    for arquivo in sorted(pasta.glob("receita_*.json"), reverse=True):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        if dados.get("_meta", {}).get("aprovada"):
            return dados.get("seletor_item")
    return None


def medir(url: str, apelido: str, seletor: str | None) -> dict:
    """Uma requisicao, com o portao do robots antes. Devolve a medicao."""
    ua = IDENTIDADES[apelido]
    veredito = conformidade.verificar(url, user_agent=ua)
    if not veredito.permitido:
        return {
            "identidade": apelido,
            "resultado": "negado_pelo_robots",
            "motivo": veredito.motivo,
        }

    espera = max(veredito.crawl_delay or 0.0, PISO_DELAY)
    inicio = time.monotonic()
    try:
        resposta = httpx.get(
            url,
            headers={"User-Agent": ua, "Accept-Language": "pt-BR,pt;q=0.9"},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
    except Exception as erro:  # rede caiu: registrar, nao mascarar
        # A pausa vale TAMBEM no caminho de erro: a requisicao SAIU, so nao
        # voltou. Ate 04/08 este `return` acontecia antes do `time.sleep`, entao a
        # replica seguinte disparava sem intervalo -- rajada exatamente quando a
        # fonte pode estar sob estresse.
        time.sleep(espera)
        return {"identidade": apelido, "resultado": "erro_de_rede", "erro": repr(erro)}

    corpo = resposta.content
    texto = resposta.text
    itens = None
    if seletor and resposta.status_code == 200:
        try:
            itens = len(BeautifulSoup(texto, "html.parser").select(seletor))
        except Exception:
            itens = None

    time.sleep(espera)
    return {
        "identidade": apelido,
        "user_agent": ua,
        "resultado": "ok",
        "status": resposta.status_code,
        "bytes": len(corpo),
        "itens": itens,
        "seletor_usado": seletor,
        "precos": len(PADRAO_PRECO.findall(texto)),
        "segundos": round(time.monotonic() - inicio, 2),
        "html": corpo,  # removido antes de serializar; gravado a parte
    }


def descobrir_shopee() -> str | None:
    """A url de julho nao foi salva: acha a primeira permitida que responda 200."""
    for url in CANDIDATAS_SHOPEE:
        veredito = conformidade.verificar(url, user_agent=HONESTO)
        if not veredito.permitido:
            print(f"  robots NEGOU {url} -- {veredito.motivo}")
            continue
        espera = max(veredito.crawl_delay or 0.0, PISO_DELAY)
        try:
            resposta = httpx.get(
                url, headers={"User-Agent": HONESTO}, timeout=TIMEOUT, follow_redirects=True
            )
        except Exception as erro:
            print(f"  erro em {url}: {erro!r}")
            time.sleep(espera)  # a requisicao saiu; a pausa vale igual
            continue
        time.sleep(espera)
        if resposta.status_code == 200:
            return url
        print(f"  {url} respondeu {resposta.status_code}")
    return None


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    condicoes = list(CONDICOES)

    print("Descobrindo rota da Shopee (a de julho nao foi registrada)...")
    url_shopee = descobrir_shopee()
    if url_shopee:
        condicoes.append(("shopee", "descoberta", url_shopee, IDENTIDADES_SHOPEE))
        print(f"  -> usando {url_shopee}")
    else:
        print("  -> nenhuma candidata permitida respondeu 200; Shopee fica de fora")

    registro = {
        "executado_em_utc": datetime.now(timezone.utc).isoformat(),
        "replicas": REPLICAS,
        "piso_delay_s": PISO_DELAY,
        "identidades": IDENTIDADES,
        "medicoes": [],
    }

    for fonte, rota, url, apelidos in condicoes:
        dominio = url.split("/")[2]
        seletor = seletor_vivo(dominio)
        print(f"\n=== {fonte}/{rota} -- {url}\n    seletor vivo: {seletor}")
        for apelido in apelidos:
            for replica in range(1, REPLICAS + 1):
                medicao = medir(url, apelido, seletor)
                html = medicao.pop("html", None)
                if html is not None and replica == 1:
                    nome = f"{carimbo}_{fonte}_{rota}_{apelido}.html"
                    (SAIDA / nome).write_bytes(html)
                    medicao["html_salvo"] = nome
                medicao.update(fonte=fonte, rota=rota, url=url, replica=replica)
                registro["medicoes"].append(medicao)
                print(
                    f"    {apelido:14} r{replica}  "
                    + (
                        f"{medicao['status']}  {medicao['bytes']:>8} B  "
                        f"itens={medicao['itens']}  precos={medicao['precos']}"
                        if medicao["resultado"] == "ok"
                        else medicao["resultado"]
                    )
                )

    destino = SAIDA / f"{carimbo}_medicoes.json"
    destino.write_text(json.dumps(registro, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"\nGravado: {destino}")
    print(f"HTMLs brutos em: {SAIDA}")


if __name__ == "__main__":
    main()
