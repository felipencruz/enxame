# -*- coding: utf-8 -*-
"""Primeira EDA descritiva (17/07): Data Understanding do CRISP-DM.

Escopo (definido em 17/07): descritiva, não o teste formal da H1 (o lead-lag exige
uma série mais longa, de 3 a 4 semanas). O conteúdo torna reproduzível, fora de um
Code node do n8n, o que foi medido em 16/07: o `sales` não é acumulador, o refresh
1x/dia, o churn de itens, a cobertura por categoria da Amazon (não garantida por
rodada) e o `titulo` nulo observado ao escrever `preparar_silver.py`. A cobertura e
o título nulo valem também para o Mercado Livre, que tem `categoria_parte_a` na
Silver desde 23/09.

Lê a Silver em memória (`preparar_silver.preparar_bronze()`), não os CSVs salvos em
`02_Dados/processado/`, para não rodar a EDA contra uma Silver desatualizada caso
`preparar_silver.py` não tenha sido executado antes.

Rodar: python 03_Analise/eda_descritiva.py
Testar: python -m pytest 03_Analise/test_eda_descritiva.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sem display: só salva PNG
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparar_silver import preparar_bronze  # noqa: E402

FIGURAS_DIR = Path(__file__).resolve().parent.parent / "02_Dados" / "processado" / "figuras"


# ---------------------------------------------------------------------------
# 1. Panorama geral das 5 fontes
# ---------------------------------------------------------------------------


def resumo_geral(tabelas: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Uma linha por fonte: linhas, snapshots distintos, período coberto."""
    linhas = []
    for nome, df in tabelas.items():
        linhas.append(
            {
                "tabela": nome,
                "linhas": len(df),
                "snapshots_distintos": df["coletado_em"].nunique(),
                "primeiro_snapshot": df["coletado_em"].min(),
                "ultimo_snapshot": df["coletado_em"].max(),
            }
        )
    return pd.DataFrame(linhas).set_index("tabela")


# ---------------------------------------------------------------------------
# 2. O `sales` da Shopee não é acumulador (medido em 16/07, formalizado aqui)
# ---------------------------------------------------------------------------


def sales_teste_primeiro_vs_ultimo(shopee: pd.DataFrame) -> dict:
    """Para cada item_id com >=2 snapshots, compara o primeiro e o último ponto.
    Um acumulador nunca cairia; a medição mostra itens cujo `sales` cai."""
    por_item = shopee.sort_values("coletado_em").groupby("item_id")["sales"]
    primeiro = por_item.first()
    ultimo = por_item.last()
    n_snapshots = shopee.groupby("item_id")["coletado_em"].nunique()
    validos = n_snapshots[n_snapshots >= 2].index
    delta = (ultimo.loc[validos] - primeiro.loc[validos])
    return {
        "n_itens_avaliados": len(validos),
        "subiu": int((delta > 0).sum()),
        "empatou": int((delta == 0).sum()),
        "caiu": int((delta < 0).sum()),
        "maior_queda_item": delta.idxmin() if len(delta) else None,
        "maior_queda_valor": float(delta.min()) if len(delta) else None,
    }


def sales_refresh_diario(shopee: pd.DataFrame) -> dict:
    """Delta entre rodadas consecutivas por item: a fração de zeros mede o refresh
    1x/dia (a fonte só atualiza dentro de uma janela; fora dela, delta = 0)."""
    ordenado = shopee.sort_values("coletado_em")
    deltas = ordenado.groupby("item_id")["sales"].diff().dropna()
    return {
        "pares_avaliados": int(len(deltas)),
        "deltas_zero": int((deltas == 0).sum()),
        "fracao_zero": float((deltas == 0).mean()) if len(deltas) else float("nan"),
    }


def sales_churn(shopee: pd.DataFrame) -> dict:
    """Quantos itens aparecem em todos os snapshots vs. num único. Mede se a série
    tem itens suficientes para lead-lag (H1), sem testar a H1 em si."""
    total_snapshots = shopee["coletado_em"].nunique()
    n_por_item = shopee.groupby("item_id")["coletado_em"].nunique()
    return {
        "total_snapshots": int(total_snapshots),
        "total_itens_distintos": int(n_por_item.shape[0]),
        "itens_em_todos_os_snapshots": int((n_por_item == total_snapshots).sum()),
        "itens_com_1_snapshot_so": int((n_por_item == 1).sum()),
    }


# ---------------------------------------------------------------------------
# 3. Amazon e Mercado Livre: cobertura por categoria e rodada, e o titulo nulo
#
# As funções desta seção valem para as duas fontes: pedem `categoria_parte_a` e
# `categoria_pagina`, que o ML também tem na Silver desde 23/09. Os nomes das saídas
# da Amazon (`amazon_*`) ficam como estão, e as do ML entram ao lado.
# ---------------------------------------------------------------------------


def cobertura_por_rodada(silver: pd.DataFrame) -> pd.DataFrame:
    """Linhas por (coletado_em, categoria_parte_a). A cobertura por categoria não é
    garantida por rodada, e esta tabela expõe onde falha.
    Linha sem `categoria_parte_a` (o ML antes de 15/07) não entra: o pivot a descarta."""
    tabela = silver.pivot_table(
        index="coletado_em",
        columns="categoria_parte_a",
        values="item_id",
        aggfunc="count",
        fill_value=0,
    )
    return tabela


def titulo_nulo_por_pool(silver: pd.DataFrame) -> pd.DataFrame:
    """Formaliza o achado de 17/07: titulo nulo em linha legítima, concentrado em
    algumas categorias/vitrines. O pool é a vitrine da Amazon ou o carrossel do ML
    (`categoria_pagina` nas duas)."""
    silver = silver.copy()
    silver["titulo_nulo"] = silver["titulo"].isna()
    resumo = (
        silver.groupby("categoria_pagina")["titulo_nulo"]
        .agg(["sum", "count"])
        .rename(columns={"sum": "titulo_nulo", "count": "total"})
    )
    resumo["taxa"] = resumo["titulo_nulo"] / resumo["total"]
    return resumo.sort_values("titulo_nulo", ascending=False)


# ---------------------------------------------------------------------------
# 4. Distribuições básicas (preço, nota) por fonte
# ---------------------------------------------------------------------------


def distribuicao_precos(tabelas_silver: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """describe() do preço de cada fonte que tem preço numérico (ML, Amazon, Shopee)."""
    campos = {"tcc_bronze_ml": "preco", "tcc_bronze_amazon": "preco", "tcc_bronze_shopee": "price"}
    linhas = {}
    for tabela, campo in campos.items():
        if tabela not in tabelas_silver:
            continue   # o ML só entra quando pedido (medição datada, até 06/10)
        serie = tabelas_silver[tabela][campo].dropna()
        linhas[tabela] = serie.describe()
    return pd.DataFrame(linhas).T


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------


def _salvar_figura(fig, nome: str) -> Path:
    FIGURAS_DIR.mkdir(parents=True, exist_ok=True)
    destino = FIGURAS_DIR / nome
    fig.savefig(destino, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return destino


def figura_trajetorias_sales(shopee: pd.DataFrame, n_itens: int = 7) -> Path:
    """Trajetórias dos itens de maior cobertura: a evidência visual de que o `sales`
    sobe e desce (não é hodômetro).

    O critério é "os N itens de maior cobertura", e não "itens presentes em todos os
    snapshots". Com série longa (81 snapshots em 30/07, o item de maior cobertura em
    79), nenhum item atravessa a série inteira por causa do churn: o filtro antigo
    devolvia vazio e a figura saía em branco sem erro, só com um `UserWarning` de
    legenda vazia. Pegar os N de maior cobertura é estável por construção, qualquer
    que seja o tamanho da série. A figura é citada como evidência do invariante
    `caiu > 0`.
    """
    n_por_item = shopee.groupby("item_id")["coletado_em"].nunique().sort_values(ascending=False)
    escolhidos = n_por_item.head(n_itens)
    if escolhidos.empty:  # só se a Shopee vier vazia: falha explícita em vez de PNG vazio
        raise ValueError("Nenhum item da Shopee para plotar: a série está vazia.")

    fig, ax = plt.subplots(figsize=(9, 5))
    for item_id, cobertura in escolhidos.items():
        serie = shopee[shopee["item_id"] == item_id].sort_values("coletado_em")
        ax.plot(serie["coletado_em"], serie["sales"], marker="o",
                label=f"{item_id} ({cobertura} snapshots)")
    total_snapshots = shopee["coletado_em"].nunique()
    ax.set_title(
        f"Trajetórias do campo `sales` — os {len(escolhidos)} itens de maior cobertura "
        f"(de {total_snapshots} snapshots)"
    )
    ax.set_xlabel("coletado_em")
    ax.set_ylabel("sales")
    ax.legend(fontsize=7, ncol=2)
    fig.autofmt_xdate()
    return _salvar_figura(fig, "sales_trajetorias.png")


def figura_cobertura(cobertura: pd.DataFrame, fonte: str = "amazon") -> Path:
    """Produtos por categoria da Parte A, por rodada: a distribuição entre rodadas, em
    boxplot. Vale para a Amazon e para o ML (o arquivo da Amazon mantém o nome).

    Boxplot e não barras por rodada: com uma barra e uma entrada de legenda por rodada,
    a figura só é legível com poucas rodadas; com cerca de 130 (Amazon) ou 255 (ML) a
    legenda cobre o gráfico inteiro. O boxplot mostra que a cobertura por categoria não
    é garantida por rodada com qualquer tamanho de série.
    """
    rotulo = {"amazon": "Amazon", "ml": "Mercado Livre"}[fonte]
    fig, ax = plt.subplots(figsize=(12, 5.5))
    cobertura.plot(kind="box", ax=ax)
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")
    ax.set_title(
        f"{rotulo}: produtos por categoria da Parte A, por rodada ({len(cobertura)} rodadas)"
    )
    ax.set_xlabel("categoria_parte_a")
    ax.set_ylabel("produtos na rodada")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    return _salvar_figura(fig, f"{fonte}_cobertura_por_rodada.png")


def figura_distribuicao_precos(tabelas_silver: dict[str, pd.DataFrame]) -> Path:
    pares = [("tcc_bronze_ml", "preco", "ML"), ("tcc_bronze_amazon", "preco", "Amazon"), ("tcc_bronze_shopee", "price", "Shopee")]
    pares = [p for p in pares if p[0] in tabelas_silver]   # sem o ML por padrão (desde 20/10)
    fig, axes = plt.subplots(1, len(pares), figsize=(4.4 * len(pares), 4))
    for ax, (tabela, campo, titulo) in zip(axes, pares):
        tabelas_silver[tabela][campo].dropna().plot(kind="hist", bins=30, ax=ax)
        ax.set_title(titulo)
        ax.set_xlabel("preço (R$)")
    fig.tight_layout()
    return _salvar_figura(fig, "distribuicao_precos.png")


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def rodar_eda(com_mercado_livre: bool = False) -> dict:
    """Roda a EDA inteira e devolve todos os resultados num dict, usado tanto pelo
    CLI quanto pelos testes.

    Sem o Mercado Livre por padrão: a fonte saiu da análise em 20/10, da Silver em
    diante. `com_mercado_livre=True` reproduz a EDA datada que o incluía (série até 06/10).
    """
    tabelas = preparar_bronze(com_mercado_livre=com_mercado_livre)
    shopee = tabelas["tcc_bronze_shopee"]
    amazon = tabelas["tcc_bronze_amazon"]

    resultado = {
        "resumo_geral": resumo_geral(tabelas),
        "sales_primeiro_vs_ultimo": sales_teste_primeiro_vs_ultimo(shopee),
        "sales_refresh_diario": sales_refresh_diario(shopee),
        "sales_churn": sales_churn(shopee),
        "amazon_cobertura_por_rodada": cobertura_por_rodada(amazon),
        "amazon_titulo_nulo_por_categoria": titulo_nulo_por_pool(amazon),
        "distribuicao_precos": distribuicao_precos(tabelas),
        "_tabelas": tabelas,
    }
    if "tcc_bronze_ml" in tabelas:
        ml = tabelas["tcc_bronze_ml"]
        resultado["ml_cobertura_por_rodada"] = cobertura_por_rodada(ml)
        resultado["ml_titulo_nulo_por_categoria"] = titulo_nulo_por_pool(ml)
    return resultado


def _main() -> None:
    resultado = rodar_eda()

    print("=== Resumo geral ===")
    print(resultado["resumo_geral"])

    print("\n=== sales: primeiro vs. último ponto (não é acumulador) ===")
    for k, v in resultado["sales_primeiro_vs_ultimo"].items():
        print(f"  {k}: {v}")

    print("\n=== sales: refresh diário ===")
    for k, v in resultado["sales_refresh_diario"].items():
        print(f"  {k}: {v}")

    print("\n=== sales: churn de itens ===")
    for k, v in resultado["sales_churn"].items():
        print(f"  {k}: {v}")

    for fonte, rotulo in (("amazon", "Amazon"), ("ml", "Mercado Livre")):
        if f"{fonte}_titulo_nulo_por_categoria" not in resultado:
            continue
        print(f"\n=== {rotulo}: titulo nulo por vitrine/carrossel (top 5) ===")
        print(resultado[f"{fonte}_titulo_nulo_por_categoria"].head(5))

    print("\n=== Distribuição de preços ===")
    print(resultado["distribuicao_precos"])

    tabelas = resultado["_tabelas"]
    caminhos = [
        figura_trajetorias_sales(tabelas["tcc_bronze_shopee"]),
        figura_cobertura(resultado["amazon_cobertura_por_rodada"], "amazon"),
        figura_distribuicao_precos(tabelas),
    ]
    # A figura do ML não é regerada: a versionada é a da série até 06/10.
    if "ml_cobertura_por_rodada" in resultado:
        caminhos.append(figura_cobertura(resultado["ml_cobertura_por_rodada"], "ml"))
    print("\n=== Figuras salvas ===")
    for c in caminhos:
        print(f"  {c}")


if __name__ == "__main__":
    _main()
