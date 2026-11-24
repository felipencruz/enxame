"""Sonda de REGRESSÃO CAMPO A CAMPO da receita do Mercado Livre — read-only, sem LLM,
sem gravação. É a "gravação desligada" que se roda antes de trocar uma receita.

POR QUE ELA EXISTE
------------------
A prova controlada do auto-reparo (29/07) registrou que três provocações do ML
convergiram para receitas com nota **0,9352**, e o `LEIA-ME.md` daquela prova as
descreveu como *"receita MELHOR que a de produção (0,7685)"*. Este é o instrumento
que confere isso contra a página **de hoje**, e não contra o texto.

O QUE ELA COMPARA — as receitas REAIS, lidas do artefato, não reconstruídas de prosa:

    producao       a que está no ar desde 15/07
    reparo_item    `item_inexistente` / `item_no_elemento_errado` → seletor_item novo
    reparo_titulo  `titulo_sumido`                                → titulo novo
    reparo_grupo   `grupo_no_titulo`                              → seletor_grupo novo
    fusao_leia_me  seletor_item novo + titulo novo JUNTOS — a "candidata" descrita no
                   LEIA-ME da prova, que **nenhum agente propôs**: ela é a fusão de dois
                   reparos de casos diferentes

O QUE ELA NÃO FAZ: não chama o LLM, não salva receita, não grava no Bronze, não
publica nem despublica nada. Uma requisição HTTP, passando pelo Agente 1 antes.

Uso, de dentro do container:
    docker exec -w /srv/enxame-api enxame-api python sonda_regressao_receita_ml.py
"""

import json
import sys
from pathlib import Path

from app import bloqueio, coleta_http, coletor
from app.agentes import analista_estrutura as ae
from app.agentes import conformidade, supervisor

DOMINIO = "www.mercadolivre.com.br"
URL = "https://www.mercadolivre.com.br/mais-vendidos/"
UA = conformidade.USER_AGENT_PADRAO
CAMPOS = ["categoria", "titulo", "preco", "preco_antigo", "desconto", "link"]

# Os seletores divergentes de cada reparo, copiados do artefato
# `02_Dados/raw/prova_auto_reparo_20260729/prova_auto_reparo_20260729T023215Z.json`
# (bloco `receita_reparada` de cada caso). Ficam aqui como DADO explícito porque o
# artefato não é embarcado no container — e porque um seletor escrito à mão a partir
# de prosa foi exatamente o defeito que esta sonda existe para não repetir.
VARIANTES = {
    "reparo_item": {"seletor_item": ".dynamic-carousel__item-container"},
    "reparo_titulo": {"campo_titulo": "h3.dynamic-carousel__title"},
    "reparo_grupo": {"seletor_grupo": ".andes-carousel-snapped__container"},
    "fusao_leia_me": {
        "seletor_item": ".dynamic-carousel__item-container",
        "campo_titulo": "h3.dynamic-carousel__title",
    },
}


def montar(base: dict, mudancas: dict) -> dict:
    r = json.loads(json.dumps(base))
    if "seletor_item" in mudancas:
        r["seletor_item"] = mudancas["seletor_item"]
    if "seletor_grupo" in mudancas:
        r["seletor_grupo"] = mudancas["seletor_grupo"]
    if "campo_titulo" in mudancas:
        r["campos"]["titulo"]["seletor"] = mudancas["campo_titulo"]
    return r


def chave(linha: dict) -> str:
    return (linha.get("link") or "").split("#")[0]


def main() -> int:
    veredito = conformidade.verificar(URL, UA)
    print(f"Agente 1: {'PERMITIDO' if veredito.permitido else 'NEGADO'} ({veredito.motivo})")
    if not veredito.permitido:
        return 1

    regra = bloqueio.volume_esperado(DOMINIO)
    html = coleta_http.buscar_html(URL, UA, piso_bytes=(regra or {}).get("piso_bytes"))
    print(f"HTML ao vivo: {len(html):,} bytes  ·  crachá {UA}")

    producao = coletor.carregar_receita_mais_recente(DOMINIO)
    print(f"receita de produção: {producao['_meta'].get('criado_em')}\n")

    receitas = {"producao": producao}
    receitas.update({nome: montar(producao, m) for nome, m in VARIANTES.items()})

    resultados = {}
    for nome, receita in receitas.items():
        linhas = ae.aplicar_receita(html, receita)
        val = ae.validar_receita(linhas, coletor._campos_da_receita(receita))
        resultados[nome] = {
            "linhas": linhas,
            "nota": supervisor.pontuar(val),
            "aprovada": ae.aprovada(val, receita),
            "itens": val["itens_encontrados"],
            "taxas": {c: val["campos"].get(c, {}).get("taxa") for c in CAMPOS},
        }

    print(f"{'variante':<15} {'itens':>6} {'nota':>7} {'aprov':>6}  "
          + " ".join(f"{c[:9]:>9}" for c in CAMPOS))
    for nome, r in resultados.items():
        taxas = " ".join(f"{(r['taxas'].get(c) or 0):>9.3f}" for c in CAMPOS)
        print(f"{nome:<15} {r['itens']:>6} {r['nota']:>7} {str(r['aprovada']):>6}  {taxas}")

    print("\nregressão linha a linha contra a produção (chave = link):")
    base = {chave(l): l for l in resultados["producao"]["linhas"]}
    resumo = {}
    for nome, r in resultados.items():
        if nome == "producao":
            continue
        atual = {chave(l): l for l in r["linhas"]}
        comuns = set(base) & set(atual)
        difs = {c: 0 for c in CAMPOS if c != "link"}
        for k in comuns:
            for c in difs:
                if (base[k].get(c) or None) != (atual[k].get(c) or None):
                    difs[c] += 1
        divergentes = {c: n for c, n in difs.items() if n}
        resumo[nome] = {
            "comuns": len(comuns),
            "perdidos": len(set(base) - set(atual)),
            "novos": len(set(atual) - set(base)),
            "valores_divergentes": divergentes,
        }
        print(f"  {nome:<15} comuns={len(comuns):>4} perdidos={resumo[nome]['perdidos']:>3} "
              f"novos={resumo[nome]['novos']:>3} | divergências: "
              f"{divergentes if divergentes else 'nenhuma'}")

    saida = {
        "url": URL,
        "user_agent": UA,
        "bytes": len(html),
        "receita_producao_criada_em": producao["_meta"].get("criado_em"),
        "variantes": {n: {k: v for k, v in r.items() if k != "linhas"}
                      for n, r in resultados.items()},
        "regressao": resumo,
    }
    destino = Path("/tmp/regressao_receita_ml.json")
    destino.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresultado em {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
