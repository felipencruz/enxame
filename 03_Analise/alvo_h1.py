# -*- coding: utf-8 -*-
"""A fundação da H1 estendida (Shopee + Amazon + Mercado Livre): o alvo por termo/dia.

Implementa as regras do alvo (§3.4 da especificação da Silver), numeradas de 1 a 9 ao
longo do módulo. As regras 1 a 8 foram escritas antes desta implementação rodar, de
propósito: regra escolhida depois de ver o resultado é racionalização, não método.

O que este módulo faz, em três passos:
  1. Join produto→termo vivo: aplica o classificador da Parte B3 (regras v1+v2+v3,
     as mesmas que geraram as sementes) aos itens diários da Shopee, da Amazon e do
     Mercado Livre. É o que liga o alvo (venda/rank, por produto) ao sinal de busca
     (por termo).
  2. Índice comum: Amazon e ML entram pelo `rank_percentil` (§2.5 e §2.6, já na
     Silver; o do ML desde 23/09, com o mesmo nome e a mesma fórmula); a Shopee ganha um
     `sales_percentil` calculado com a mesma fórmula, dentro do pool que a fonte serve
     numa observação (a vitrine, o carrossel, o top do dia). Um ponto por item por dia
     (a última observação do dia, UTC).
  3. Alvo por termo/dia: média dos percentis dos itens do termo, por fonte, e a
     média simples das fontes disponíveis como alvo unificado, sem imputar zero para
     fonte ausente.

Regra 9 (15/09/2026): o Mercado Livre é a terceira fonte de alvo, no mesmo patamar de
Amazon e Shopee. Antes ele entrava só nas dimensões de oferta e preço do Score, porque o
Bronze não tem coluna de posição; a posição, porém, é derivável da ordem de inserção,
como provado contra o HTML bruto. O `alvo_ml` usa a mesma régua da Amazon: percentil
dentro do pool (aqui o pool é o carrossel), média por termo-dia.
`construir_alvo(..., com_mercado_livre=False)` reproduz o alvo de duas fontes, o que
mantém o experimento 1 do lead-lag (08/09, pré-registrado) reproduzível depois da
mudança da fundação; a emenda está declarada na §8b do `protocolo_lead_lag_h1.py`. Desde
30/09 são duas chaves: a regra de Artes e entretenimento mudou o classificador (§8f), e o
experimento 1 exato é `construir_alvo(..., com_mercado_livre=False, com_regras_artes=False)`.

20/10/2026: o Mercado Livre saiu, e o padrão voltou a ser Shopee + Amazon. A fonte parou
de gravar em 06/10 (verificação de conta; HTTP 500 desde 19/10) e o coletor seguiu
tentando; em 20/10 a fonte foi retirada do projeto, e o Bronze fica como exemplo. O alvo
de três fontes continua reproduzível com `com_mercado_livre=True`, com a série do ML
cortada em 06/10: é o que sustenta as medições datadas (os pares do achado ⑤ e a
reanálise de 17/09). A emenda do experimento 2 é a §8h do `protocolo_lead_lag_h1.py`.

O que este módulo não faz, por decisão: não testa a H1. O que sai daqui é a fundação e
o primeiro olhar descritivo sobre ela; o teste do lead-lag está em
`experimento_lead_lag_h1.py`.

Lê a Silver em memória (`preparar_silver.preparar_bronze()`), nunca o CSV salvo em
`02_Dados/processado/`, mesmo cuidado do `eda_descritiva.py` (evita rodar contra uma
Silver desatualizada).

Rodar:  python 03_Analise/alvo_h1.py
Testar: python -m pytest 03_Analise/test_alvo_h1.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sem display: só salva PNG
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parte_b3_refresh_multi_fonte import REGRAS_COMP_SEM_ARTES, classificar  # noqa: E402
from parte_b_mineracao_seeds import norm  # noqa: E402
from preparar_silver import preparar_bronze  # noqa: E402

PROCESSADO_DIR = Path(__file__).resolve().parent.parent / "02_Dados" / "processado"
FIGURAS_DIR = PROCESSADO_DIR / "figuras"

SAIDA_TERMO_DIA = PROCESSADO_DIR / "tcc_alvo_h1_por_termo_dia.csv"
SAIDA_TERMO_DIA_BALANCEADO = PROCESSADO_DIR / "tcc_alvo_h1_por_termo_dia_janela_comum.csv"
SAIDA_ITEM_DIA = PROCESSADO_DIR / "tcc_alvo_h1_por_item_dia.csv"


# ---------------------------------------------------------------------------
# Regra 1: join produto -> termo (classificador da Parte B3)
# ---------------------------------------------------------------------------


def classificar_titulos(titulos: pd.Series, com_regras_artes: bool = True) -> pd.DataFrame:
    """Aplica o classificador da B3 a uma coluna de títulos.

    `com_regras_artes=False` usa o classificador de antes de 30/09, sem a regra de "Artes e
    entretenimento"; é o que reproduz o alvo do experimento 1 e da reanálise.

    Devolve um DataFrame com `termo` e `categoria_termo` (NaN quando o título é órfão
    ou nulo). Título nulo existe de verdade: 82% da vitrine Games e Consoles da Amazon
    (§3.2.1); esses itens ficam sem termo, o que é ausência declarada, não zero.

    O cache por título normalizado importa: são ~14 mil linhas de Amazon contra ~200
    regexes, e a maioria dos títulos se repete entre snapshots.
    """
    regras = None if com_regras_artes else REGRAS_COMP_SEM_ARTES
    cache: dict[str, tuple] = {}
    termos, categorias = [], []
    for titulo in titulos:
        if not isinstance(titulo, str) or not titulo.strip():
            termos.append(None)
            categorias.append(None)
            continue
        chave = norm(titulo)
        if chave not in cache:
            termo, categoria, _padrao = classificar(chave, regras)
            cache[chave] = (termo, categoria)
        termo, categoria = cache[chave]
        termos.append(termo)
        categorias.append(categoria)
    return pd.DataFrame(
        {"termo": termos, "categoria_termo": categorias}, index=titulos.index
    )


# ---------------------------------------------------------------------------
# Regras 2 e 3: o índice comum (percentil dentro do pool servido numa observação)
# ---------------------------------------------------------------------------


def percentil_no_pool(
    df: pd.DataFrame, coluna: str, grupo: list[str], maior_e_melhor: bool = True
) -> pd.Series:
    """Percentil 1.0 = melhor, 0.0 = pior, dentro de cada `grupo`.

    Mesma fórmula do §2.5 (`1 - (rank-1)/(n-1)`, com `n == 1` -> 1.0), aplicada aqui ao
    `sales` da Shopee para que os dois sinais entrem no alvo com a mesma construção,
    e não com duas normalizações diferentes chamadas depois de "índice comum".

    Empate vira posto médio (regra 3): o `sales` empata muito (vários itens com o
    mesmo valor), o `rank` da Amazon não empata nunca.
    """
    postos = df.groupby(grupo)[coluna].rank(
        ascending=not maior_e_melhor, method="average"
    )
    n = df.groupby(grupo)[coluna].transform("count")
    denominador = (n - 1).clip(lower=1)
    percentil = 1 - (postos - 1) / denominador
    return percentil.where(n > 1, 1.0)


# ---------------------------------------------------------------------------
# Regras 4 e 5: um ponto por item por dia
# ---------------------------------------------------------------------------


def _ultimo_do_dia(df: pd.DataFrame, chave_item: str = "item_id") -> pd.DataFrame:
    """Regra 4: mantém só as linhas do último `coletado_em` de cada (item, dia UTC).

    Pode devolver mais de uma linha por item-dia quando o item aparece em duas vitrines
    no mesmo instante (Amazon); a regra 5 resolve isso, logo em seguida.
    """
    out = df.copy()
    out["dia"] = out["coletado_em"].dt.date
    ultimo = out.groupby([chave_item, "dia"])["coletado_em"].transform("max")
    return out[out["coletado_em"] == ultimo].copy()


def itens_dia_shopee(shopee_silver: pd.DataFrame, com_regras_artes: bool = True) -> pd.DataFrame:
    """Um ponto por (item, dia) da Shopee, com `sales`, `sales_percentil` e `termo`."""
    df = shopee_silver.copy()
    df["sales_percentil"] = percentil_no_pool(df, "sales", ["coletado_em"])
    df = pd.concat([df, classificar_titulos(df["product_name"], com_regras_artes)], axis=1)

    diario = _ultimo_do_dia(df)
    # Regra 5 (aqui é trivial: a Shopee não tem vitrine, então o dedup de paginação da
    # Silver já garantiu um item_id por snapshot; este drop_duplicates é redundância
    # defensiva contra uma mudança futura no coletor).
    diario = diario.drop_duplicates(subset=["item_id", "dia"], keep="last")
    return diario[
        [
            "item_id",
            "dia",
            "coletado_em",
            "product_name",
            "termo",
            "categoria_termo",
            "sales",
            "sales_percentil",
            "price",
        ]
    ].reset_index(drop=True)


def itens_dia_amazon(amazon_silver: pd.DataFrame, com_regras_artes: bool = True) -> pd.DataFrame:
    """Um ponto por (item, dia) da Amazon, com `rank_percentil` e `termo`.

    Regra 5: quando o mesmo item aparece em duas `categoria_parte_a` no mesmo instante
    (os 5 casos da §2.4, como a cadeira gamer que é Móveis e Computadores), sobrevive o
    pior percentil. É a mesma postura fail-closed do dedup da §2.3: na dúvida, a
    leitura que não infla.
    """
    df = amazon_silver.copy()
    df = pd.concat([df, classificar_titulos(df["titulo"], com_regras_artes)], axis=1)

    diario = _ultimo_do_dia(df)
    diario = diario.sort_values("rank_percentil", ascending=True)
    diario = diario.drop_duplicates(subset=["item_id", "dia"], keep="first")
    return diario[
        [
            "item_id",
            "dia",
            "coletado_em",
            "titulo",
            "termo",
            "categoria_termo",
            "categoria_parte_a",
            "categoria_pagina",
            "rank",
            "rank_percentil",
            "preco",
        ]
    ].reset_index(drop=True)


def itens_dia_ml(ml_silver: pd.DataFrame, com_regras_artes: bool = True) -> pd.DataFrame:
    """Um ponto por (item, dia) do ML, com `rank_percentil` e `termo`: desde 23/09, é o
    mesmo tratamento de `itens_dia_amazon` aplicado ao ML.

    A Silver do ML entrega `rank` e `rank_percentil` com os mesmos nomes e a mesma
    fórmula da Amazon (`preparar_silver.preparar_ml`), e o que resta aqui é exatamente o
    que a Amazon recebe: classificar o título, regra 4 (`_ultimo_do_dia`) e regra 5 (item
    em dois carrosséis no mesmo instante: sobrevive o pior percentil).

    A função devolve `categoria_termo`, além de `categoria_pagina`: sem ela, termo
    observado só no ML ficaria sem categoria no alvo, sem aviso (176 termo-dias em 23/09).

    Linhas sem `rank_percentil` (rodadas anteriores a 15/07, sem carrossel) não entram:
    sem posição não há alvo.
    """
    ml = ml_silver[ml_silver["rank_percentil"].notna()].copy()
    ml["coletado_em"] = pd.to_datetime(ml["coletado_em"])
    ml = pd.concat(
        [ml.reset_index(drop=True),
         classificar_titulos(ml["titulo"], com_regras_artes).reset_index(drop=True)],
        axis=1,
    )
    diario = _ultimo_do_dia(ml)
    diario = diario.sort_values("rank_percentil", ascending=True).drop_duplicates(
        subset=["item_id", "dia"], keep="first"
    )
    return diario[
        [
            "item_id",
            "dia",
            "coletado_em",
            "titulo",
            "termo",
            "categoria_termo",
            "categoria_parte_a",
            "categoria_pagina",
            "rank",
            "rank_percentil",
            "preco",
        ]
    ].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Regras 6, 7 e 8: o alvo por termo/dia
# ---------------------------------------------------------------------------


def alvo_por_termo_dia(
    itens_shopee: pd.DataFrame,
    itens_amazon: pd.DataFrame,
    itens_ml: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Junta as fontes de venda num alvo por (termo, dia).

    Regra 6: média dos percentis dos itens do termo naquele dia (o máximo e o n_itens
    saem junto, para quem quiser ler "o melhor representante do termo").
    Regra 7: alvo unificado = média simples das fontes disponíveis, sem imputar zero.
    Regra 8: termo-dia sem item observado não gera linha (é `outer` join entre o que
    cada fonte observou, não um grid completo termo × dia).

    Regra 9 (15/09/2026): o Mercado Livre entra como terceira fonte, no mesmo patamar das
    outras duas, depois de a posição no carrossel ser recuperada. Antes ele entrava só nas
    dimensões de oferta e preço do Score. O `alvo_ml` é construído com a mesma régua da
    Amazon (percentil de posição dentro do pool, média por termo-dia), e a regra 7 já
    generalizava: "média das fontes disponíveis" não fixa o número de fontes.

    O custo, medido antes de aplicar: cada fonte que entra reduz a variância do unificado
    por composição, não por mercado. Nos termo-dia em que as três observam, o desvio-padrão
    cai de 0,1519 (duas) para 0,1256 (três). E a série passa a ter três composições, não
    duas: Shopee sozinha até 14/07, +ML em 15/07, +Amazon em 16/07.

    Passar `itens_ml=None` reproduz o alvo de duas fontes, o que mantém o experimento 1
    do lead-lag (08/09) reproduzível. Mudar o alvo depois de um resultado é o que um
    pré-registro existe para impedir; por isso a mudança é uma emenda declarada (§8b do
    `protocolo_lead_lag_h1.py`), e o experimento 1 continua sendo lido com o alvo que
    tinha quando rodou.
    """
    sh = itens_shopee[itens_shopee["termo"].notna()]
    am = itens_amazon[itens_amazon["termo"].notna()]
    ml = itens_ml[itens_ml["termo"].notna()] if itens_ml is not None else None

    g_sh = (
        sh.groupby(["termo", "dia"])
        .agg(
            alvo_shopee=("sales_percentil", "mean"),
            alvo_shopee_max=("sales_percentil", "max"),
            n_itens_shopee=("item_id", "nunique"),
            sales_total=("sales", "sum"),
            sales_mediana=("sales", "median"),
        )
        .reset_index()
    )
    g_am = (
        am.groupby(["termo", "dia"])
        .agg(
            alvo_amazon=("rank_percentil", "mean"),
            alvo_amazon_max=("rank_percentil", "max"),
            n_itens_amazon=("item_id", "nunique"),
        )
        .reset_index()
    )

    juntos = g_sh.merge(g_am, on=["termo", "dia"], how="outer")

    colunas_de_alvo = ["alvo_shopee", "alvo_amazon"]
    colunas_de_n = ["n_itens_shopee", "n_itens_amazon"]
    if ml is not None:
        g_ml = (
            ml.groupby(["termo", "dia"])
            .agg(
                alvo_ml=("rank_percentil", "mean"),
                alvo_ml_max=("rank_percentil", "max"),
                n_itens_ml=("item_id", "nunique"),
            )
            .reset_index()
        )
        juntos = juntos.merge(g_ml, on=["termo", "dia"], how="outer")
        colunas_de_alvo.append("alvo_ml")
        colunas_de_n.append("n_itens_ml")

    # Regra 7: média das fontes disponíveis (NaN é ausência, não zero; o `mean` do
    # pandas sobre o eixo das colunas já ignora NaN, que é o comportamento desejado).
    juntos["alvo_unificado"] = juntos[colunas_de_alvo].mean(axis=1)
    nomes = [c.replace("alvo_", "") for c in colunas_de_alvo]
    juntos["fontes"] = juntos.apply(
        lambda linha: "+".join(
            nome for nome, coluna in zip(nomes, colunas_de_alvo) if pd.notna(linha[coluna])
        ),
        axis=1,
    )
    for coluna in colunas_de_n:
        juntos[coluna] = juntos[coluna].fillna(0).astype(int)

    fontes_de_categoria = [sh[["termo", "categoria_termo"]], am[["termo", "categoria_termo"]]]
    if ml is not None:
        # Sem teste de presença da coluna: se `categoria_termo` faltar, a execução deve
        # falhar, em vez de deixar o termo só-ML sem categoria em silêncio.
        fontes_de_categoria.append(ml[["termo", "categoria_termo"]])
    categorias = (
        pd.concat(fontes_de_categoria)
        .drop_duplicates("termo")
        .set_index("termo")["categoria_termo"]
    )
    juntos["categoria"] = juntos["termo"].map(categorias)

    return juntos.sort_values(["termo", "dia"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# O primeiro olhar descritivo (não é o teste da H1)
# ---------------------------------------------------------------------------


# A janela da cobertura vigiada (26/08). Ver `cobertura_do_join`.
JANELA_COBERTURA_DIAS = 14


def cobertura_do_join(
    itens: pd.DataFrame,
    coluna_titulo: str,
    dias: int | None = None,
    desde: str | None = None,
    ate: str | None = None,
) -> dict:
    """Quanto do que a fonte serve por dia chega a ter termo: o número que decide se
    a H1 tem material, e que precisa ser reportado junto com qualquer resultado dela.

    `dias` recorta os N últimos dias da série; `desde`/`ate` recortam uma janela fixa.

    Por que a janela existe (medido em 26/08). Sem recorte, isto é uma média acumulada
    desde 09/07, e a média acumulada de uma série que cresce converge para o valor
    corrente: ela desce sozinha enquanto nada piora. Foi o observado: 0,9297 em 13/07,
    0,8442 em 13/08 e 0,8255 em 26/08, cruzando 0,90 em 30/07, 0,85 em 12/08 e 0,83 em
    21/08. Lida como tendência, essa curva sugere que o join está se deteriorando, o que
    não é o caso.

    A cobertura corrente estava estável no mês anterior a 26/08: 7 dias 0,7598 · 14 dias
    0,7572 · 21 dias 0,7678 · 30 dias 0,7620. O que houve foi um degrau entre 27/07 e
    01/08 (~0,92 → ~0,76) e estabilidade depois.

    A causa não é o join: o classificador é determinístico sobre o título, e 1 de 1.037
    itens muda de estado na série inteira. É composição: itens que entraram a partir de
    27/07 têm cobertura 0,7083 contra 0,8715 dos anteriores; dos 72 órfãos da última
    semana, 53 apareceram há ≤14 dias. O bestseller da Shopee girou para fora do
    vocabulário de termos.

    Piso fixo sobre o acumulado acaba sempre reprovando com o tempo. A vigilância usa a
    janela; a do código usa a janela datada (ver `test_alvo_h1.py`).
    """
    if dias is not None or desde is not None or ate is not None:
        dia = pd.to_datetime(itens["dia"])
        recorte = pd.Series(True, index=itens.index)
        if dias is not None:
            recorte &= dia >= dia.max() - pd.to_timedelta(dias, unit="D")
        if desde is not None:
            recorte &= dia >= pd.Timestamp(desde)
        if ate is not None:
            recorte &= dia < pd.Timestamp(ate)
        itens = itens[recorte]
    total = len(itens)
    sem_titulo = int(itens[coluna_titulo].isna().sum())
    com_termo = int(itens["termo"].notna().sum())
    return {
        "itens_dia": total,
        "sem_titulo": sem_titulo,
        "com_termo": com_termo,
        "cobertura": com_termo / total if total else float("nan"),
        "termos_distintos": int(itens["termo"].nunique()),
    }


def concordancia_categoria_governada(itens: pd.DataFrame) -> dict:
    """Confere a categoria que o classificador deduz do título contra a categoria
    governada do pool da fonte: a vitrine da Amazon (`tcc_amazon_vitrines`) ou, desde
    23/09, o carrossel do ML (`preparar_silver._MAPA_CARROSSEL_ML_CATEGORIA`).

    É uma validação externa sem custo: o classificador nasceu de títulos, a vitrine vem
    de uma tabela governada; se concordassem por acaso, concordariam pouco.

    As duas taxas não são diretamente comparáveis: os dez carrosséis do ML caem em 6
    categorias (quatro deles em `Eletrônicos`: Celulares, Eletrônicos, Games e
    Informática), enquanto a Amazon tem 22 vitrines em 14; um mapa mais grosso concorda
    mais por construção.
    No ML ela não é validação independente, por construção: em 23/09 o mapa carrossel →
    categoria foi escolhido pela categoria onde cai a maioria dos produtos do carrossel,
    segundo este mesmo classificador. Medir depois a concordância entre os dois é usar o
    instrumento que fez a escolha para validá-la; o valor sobe por definição (75,1% →
    88,3% só pela troca de `Esportes e Fitness`). Na Amazon o mapa é governado
    externamente (`tcc_amazon_vitrines`, 15/07) e a validação vale; no ML ela é
    descrição, não prova.
    """
    com_termo = itens[itens["termo"].notna()]
    iguais = (com_termo["categoria_termo"] == com_termo["categoria_parte_a"]).sum()
    discordantes = (
        com_termo[com_termo["categoria_termo"] != com_termo["categoria_parte_a"]]
        .groupby(["categoria_parte_a", "categoria_termo"])
        .size()
        .sort_values(ascending=False)
    )
    return {
        "avaliados": int(len(com_termo)),
        "concordam": int(iguais),
        "taxa": float(iguais / len(com_termo)) if len(com_termo) else float("nan"),
        "top_discordancias": discordantes.head(8),
    }


def perfil_das_series(alvo: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por termo: quantos dias de série tem em cada fonte, e no total.

    As fontes saem das colunas presentes, e o resumo é `n_fontes`. Uma lista fixa de
    fontes deixaria de fora o Mercado Livre (regra 9): termo observado só por ele
    sairia com as contagens das outras em zero.
    """
    colunas = [c for c in ("alvo_shopee", "alvo_amazon", "alvo_ml") if c in alvo.columns]
    agregados = {
        "dias": ("dia", "nunique"),
        "primeiro_dia": ("dia", "min"),
        "ultimo_dia": ("dia", "max"),
        "alvo_medio": ("alvo_unificado", "mean"),
    }
    for coluna in colunas:
        agregados[f"dias_{coluna.replace('alvo_', '')}"] = (coluna, "count")
    perfil = alvo.groupby("termo").agg(**agregados).reset_index()
    contagens = perfil[[f"dias_{c.replace('alvo_', '')}" for c in colunas]]
    perfil["n_fontes"] = (contagens > 0).sum(axis=1)
    perfil["em_mais_de_uma_fonte"] = perfil["n_fontes"] > 1
    return perfil.sort_values(["dias", "termo"], ascending=[False, True])


def _spearman(x: pd.Series, y: pd.Series) -> float:
    """Spearman = Pearson sobre os postos, implementado diretamente: o
    `method="spearman"` do pandas importa scipy, que não está no `requirements-dev.txt`,
    e uma dependência nova não se justifica por uma linha de correlação."""
    return float(x.rank().corr(y.rank()))


def concordancia_entre_fontes(alvo: pd.DataFrame, a: str = "shopee", b: str = "amazon") -> dict:
    """Nos termo-dia em que as duas fontes `a` e `b` observaram, os percentis andam juntos?

    Vale para qualquer par (`a`/`b` em `shopee`, `amazon`, `ml`), desde 23/09. O padrão
    continua sendo Shopee × Amazon, com as mesmas chaves de saída. Os três pares juntos:
    `concordancia_todos_os_pares`.

    Não é a H1 (que é busca × venda, com defasagem). É a checagem de sanidade do
    índice comum, e ela precisa de três cuidados, porque o número ingênuo engana:

    1. Pseudo-replicação: o mesmo termo aparece em vários dias, então correlacionar
       os pares termo-dia conta o mesmo termo várias vezes. Por isso sai também a
       correlação entre as médias por termo, com o IC95 (Fisher), que é o número a
       citar.
    2. Confundidor medido: o nº de itens do termo empurra a média do percentil. Sai
       como `spearman_com_n_itens_*`.
       Este número é empilhado (termo-dia) e mistura duas coisas: a diferença entre
       termos e a variação dentro de cada termo ao longo dos dias. Medido separando
       (24/09): na Amazon o empilhado de +0,04 esconde +0,44 entre e −0,30 dentro
       (mediana por termo); no ML o +0,24 é quase todo entre (+0,55), com o dentro perto
       de zero. O "sinal oposto" entre fontes é leitura do empilhado e não deve ser
       citado. O componente dentro do termo é o que interessa à H1, e ele troca de sinal
       com o agregador (média cai, máximo sobe, quando entram itens): é composição, não
       mercado.
    3. Sensibilidade ao agregador: o mesmo cálculo com o máximo em vez da média. Se
       a conclusão mudasse com o agregador, seria um artefato da regra 6. Isto é relato,
       não escolha: a regra 6 é a média, declarada antes de medir.
    """
    # Seleciona pela presença das duas colunas, nunca pela string `fontes`. Com três
    # fontes, o termo-dia em que as três observam é `"shopee+amazon+ml"`; filtrar por
    # `fontes == "shopee+amazon"` mediria o par só onde o ML não observou, uma
    # subpopulação escolhida pelo dado (o número publicado iria de +0,0232 para −0,0206
    # sem mudança de método). Comparação entre fontes se faz na interseção delas, e a
    # interseção se lê nas colunas.
    ca, cb = f"alvo_{a}", f"alvo_{b}"
    if ca not in alvo.columns or cb not in alvo.columns:
        return {"pares": 0, "spearman_pares": float("nan")}
    ambos = alvo[alvo[ca].notna() & alvo[cb].notna()]
    if len(ambos) < 5:
        return {"pares": int(len(ambos)), "spearman_pares": float("nan")}

    por_termo = ambos.groupby("termo").agg(x=(ca, "mean"), y=(cb, "mean"))
    n = len(por_termo)
    rho = _spearman(por_termo["x"], por_termo["y"])
    if n > 3 and abs(rho) < 1:
        fisher = 0.5 * math.log((1 + rho) / (1 - rho))
        margem = 1.96 / math.sqrt(n - 3)
        ic = (math.tanh(fisher - margem), math.tanh(fisher + margem))
    else:
        ic = (float("nan"), float("nan"))

    return {
        "pares": int(len(ambos)),
        "termos": int(n),
        "spearman_pares": _spearman(ambos[ca], ambos[cb]),
        "spearman_por_termo": rho,
        "ic95_por_termo": (round(ic[0], 3), round(ic[1], 3)),
        "spearman_agregando_por_maximo": _spearman(ambos[f"{ca}_max"], ambos[f"{cb}_max"]),
        # o confundidor: medido nas duas fontes do par, qualquer que seja
        f"spearman_com_n_itens_{a}": _spearman(ambos[ca], ambos[f"n_itens_{a}"]),
        f"spearman_com_n_itens_{b}": _spearman(ambos[cb], ambos[f"n_itens_{b}"]),
    }


# A ordem importa: é a ordem em que a sequência aleatória das permutações é consumida,
# e ela é a mesma do `ordem_carrossel_ml.concordancia_tres_fontes` de 15/09; trocar a
# ordem mudaria o nulo de cada par sem que nada no método mudasse.
PARES_DE_FONTES = (("shopee", "amazon"), ("shopee", "ml"), ("amazon", "ml"))


def concordancia_todos_os_pares(
    alvo: pd.DataFrame, permutacoes: int = 1000, semente: int = 42
) -> dict:
    """Os três pares de fontes de venda, cada um contra o próprio nulo (23/09).

    Cada par é o `concordancia_entre_fontes` (mesma seleção por colunas, mesmo IC de
    Fisher, mesmo confundidor) mais o nulo por permutação do pareamento termo↔termo.
    Cada par é comparado ao seu próprio nulo porque o N difere entre eles. A mesma medida
    existe em `ordem_carrossel_ml.concordancia_tres_fontes`, base do achado ⑤.

    Par cuja fonte não está no `alvo` (ex.: o alvo de duas fontes) é omitido; par com
    menos de 5 termo-dia sai como `{"pares": n}`, sem IC, e a trava do teste exige IC.
    """
    rng = np.random.default_rng(semente)
    saida = {}
    for a, b in PARES_DE_FONTES:
        if f"alvo_{a}" not in alvo.columns or f"alvo_{b}" not in alvo.columns:
            continue
        nome = f"{a}_x_{b}"
        base = concordancia_entre_fontes(alvo, a, b)
        if "termos" not in base:
            saida[nome] = {"pares": base["pares"]}
            continue
        ambos = alvo[alvo[f"alvo_{a}"].notna() & alvo[f"alvo_{b}"].notna()]
        por_termo = ambos.groupby("termo").agg(x=(f"alvo_{a}", "mean"), y=(f"alvo_{b}", "mean"))
        obs = base["spearman_por_termo"]
        nulos = np.array(
            [
                _spearman(por_termo["x"], pd.Series(rng.permutation(por_termo["y"].values), index=por_termo.index))
                for _ in range(permutacoes)
            ]
        )
        saida[nome] = {
            **base,
            "pares_termo_dia": base["pares"],
            "ic95": base["ic95_por_termo"],
            "nulo_media": round(float(nulos.mean()), 4),
            "nulo_desvio": round(float(nulos.std()), 4),
            "z_contra_o_proprio_nulo": round(float((obs - nulos.mean()) / nulos.std()), 2),
            "p_empirico_bilateral": round(float((np.abs(nulos) >= abs(obs)).mean()), 3),
        }
    return saida


def data_minima_comum(*conjuntos: pd.DataFrame) -> "pd.Timestamp.date":
    """A primeira data em que todas as fontes já observavam: o início do painel balanceado.

    É o máximo dos mínimos, não o mínimo: se a Shopee começa em 09/07 e a Amazon em
    16/07 (a troca de rota), o painel só fica completo a partir de 16/07.
    """
    return max(df["dia"].min() for df in conjuntos)


def aplicar_janela_comum(*conjuntos: pd.DataFrame) -> tuple:
    """Corta todos os conjuntos na `data_minima_comum`: o painel balanceado.

    Por que existe (e por que não é o padrão): o painel desbalanceado produz o artefato
    medido em `mudanca_de_regime`. Antes de 16/07 o alvo unificado é uma fonte só, depois
    são duas, e a variabilidade cai por composição. Cortar na data comum elimina esse
    artefato por construção, e é o dataset adequado para comparar as fontes entre si.

    O custo, medido em 22/07: a Shopee perde 7 dos 14 dias (45,7% das linhas) e o
    Suggest, 7 dias (26,3%). Para o lead-lag isso é caro no lugar errado: a busca é a
    variável líder, e truncá-la remove exatamente as defasagens que o teste procura. Por
    isso o corte se aplica ao painel do alvo, e a série de busca é lida inteira (§3.5 da
    especificação da Silver).
    """
    corte = data_minima_comum(*conjuntos)
    return tuple(df[df["dia"] >= corte].copy() for df in conjuntos), corte


def mudanca_de_regime(alvo: pd.DataFrame, corte: str = "2026-07-16") -> dict:
    """A armadilha de série temporal do `alvo_unificado`, medida.

    Antes do `corte` (a entrada da Amazon, 16/07, a troca de rota) o alvo unificado é
    a Shopee sozinha; depois, a média de mais de uma fonte numa parte das linhas.
    Média de vários sinais varia menos que um sinal só; então a variabilidade cai por
    troca de instrumento, não por mudança de mercado.

    A fração multifonte é lida das colunas, não do rótulo `fontes`. Com o ML (15/09), o
    termo-dia em que as três observam vira `"shopee+amazon+ml"`, e os pares novos
    (`shopee+ml`, `amazon+ml`) não casariam com `"shopee+amazon"`: medido em 17/09, a
    leitura pelo rótulo cairia de 0,2885 para 0,0804, quando a fração com mais de uma
    fonte subiu de 0,1623 para 0,3809. O nome de cada campo diz o que ele mede.

    O controle é o próprio `alvo_shopee`, que atravessa o corte sem mudar de composição:
    se a variabilidade do controle cair junto, a explicação é o mercado; se só a do unificado
    cair, é a composição. Comparação restrita aos termos presentes nos dois regimes,
    senão a troca de amostra explicaria qualquer coisa.

    Este número é citado na §3.4 da especificação da Silver, e por isso tem de ser
    remedível por código.
    """
    df = alvo.copy()
    df["dia"] = pd.to_datetime(df["dia"])
    limite = pd.Timestamp(corte)
    antes, depois = df[df["dia"] < limite], df[df["dia"] >= limite]
    comuns = set(antes["termo"]) & set(depois["termo"])
    if not comuns:
        # É o caso do painel balanceado (`--janela-comum`): não existe "antes" do corte,
        # porque o artefato foi eliminado por construção. Não é falha: é o efeito.
        return {"corte": corte, "termos_nos_dois_regimes": 0, "nao_aplicavel": True}
    a, d = antes[antes["termo"].isin(comuns)], depois[depois["termo"].isin(comuns)]
    colunas = [c for c in ("alvo_shopee", "alvo_amazon", "alvo_ml") if c in d.columns]
    n_fontes = d[colunas].notna().sum(axis=1)
    return {
        "corte": corte,
        "termos_nos_dois_regimes": len(comuns),
        "fontes_do_painel": [c.replace("alvo_", "") for c in colunas],
        "dp_unificado_antes": float(a["alvo_unificado"].std()),
        "dp_unificado_depois": float(d["alvo_unificado"].std()),
        "dp_shopee_antes": float(a["alvo_shopee"].std()),
        "dp_shopee_depois": float(d["alvo_shopee"].std()),
        "fracao_multifonte_depois": float((n_fontes > 1).mean()),
        "fracao_uma_fonte_depois": float((n_fontes == 1).mean()),
        "fracao_todas_as_fontes_depois": float((n_fontes == len(colunas)).mean()),
    }


def pool_intracategoria_shopee(itens_shopee: pd.DataFrame) -> dict:
    """Por que o percentil da Shopee é dentro do dia e não dentro da categoria.

    A normalização intra-categoria é o princípio do Score (Guia §3), então a pergunta
    óbvia é por que o alvo não a usa em todas as fontes. A resposta é de tamanho de pool:
    a Amazon serve ~50 itens por vitrine (que já é quase uma categoria) e o ML serve 10 a
    20 por carrossel (idem, dez carrosséis por departamento); a Shopee serve ~50 por dia
    no total, espalhados por ~15 categorias. Esta função mede o pool que a
    normalização intra-categoria teria na Shopee; é o que sustenta a limitação
    declarada no §3.4 com medição, e não com preferência.
    """
    com_categoria = itens_shopee[itens_shopee["categoria_termo"].notna()]
    pools = com_categoria.groupby(["coletado_em", "categoria_termo"]).size()
    return {
        "pools_avaliados": int(len(pools)),
        "itens_por_pool_mediana": float(pools.median()),
        "fracao_de_pools_com_ate_3_itens": float((pools <= 3).mean()),
    }


def casamento_com_a_busca(alvo: pd.DataFrame, suggest_silver: pd.DataFrame) -> dict:
    """Dos termos que têm alvo, quantos têm série de busca (Suggest), e por quantos
    dias as duas séries coexistem. É o gargalo real da H1, e tem que sair explícito."""
    suggest = suggest_silver.copy()
    suggest["dia"] = suggest["coletado_em"].dt.date
    dias_busca = suggest.groupby("termo_semente")["dia"].nunique()

    termos_alvo = set(alvo["termo"].dropna())
    com_busca = {t for t in termos_alvo if t in dias_busca.index}

    dias_alvo = alvo.groupby("termo")["dia"].nunique()
    # Dict, e não duas listas paralelas: colher os valores na ordem de iteração de
    # `com_busca` (um set) e montar a Série com `index=sorted(com_busca)` desalinharia
    # índice e valores, porque ordem de set não é ordem alfabética. Os agregados (mediana
    # e o `>= 7`) não dependem de ordem, mas a leitura por termo depende.
    contagem = {}
    for termo in sorted(com_busca):
        dias_t = set(alvo[alvo["termo"] == termo]["dia"])
        dias_b = set(suggest[suggest["termo_semente"] == termo]["dia"])
        contagem[termo] = len(dias_t & dias_b)
    sobreposicao = pd.Series(contagem, dtype=int) if contagem else pd.Series(dtype=int)

    return {
        "termos_com_alvo": len(termos_alvo),
        "termos_com_alvo_e_busca": len(com_busca),
        "termos_sem_serie_de_busca": sorted(termos_alvo - com_busca),
        "dias_sobrepostos_mediana": float(sobreposicao.median()) if len(sobreposicao) else float("nan"),
        "termos_com_7_ou_mais_dias_sobrepostos": int((sobreposicao >= 7).sum()),
        "dias_alvo_mediana": float(dias_alvo.median()) if len(dias_alvo) else float("nan"),
    }


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------


def _salvar_figura(fig, nome: str) -> Path:
    FIGURAS_DIR.mkdir(parents=True, exist_ok=True)
    destino = FIGURAS_DIR / nome
    fig.savefig(destino, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return destino


def figura_cobertura_por_dia(alvo: pd.DataFrame) -> Path:
    """Quantos termos têm alvo em cada dia, por fonte: mostra a assimetria de série
    (a Amazon só existe desde 16/07) sem precisar de tabela.

    As fontes saem das colunas presentes, para que a figura inclua toda fonte que
    compõe o unificado (o ML, quando presente)."""
    agregados = {
        nome: (f"alvo_{nome}", "count")
        for nome in ("shopee", "amazon", "ml")
        if f"alvo_{nome}" in alvo.columns
    }
    agregados["unificado"] = ("alvo_unificado", "count")
    por_dia = alvo.groupby("dia").agg(**agregados)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    por_dia.plot(ax=ax, marker="o")
    ax.set_title("Termos com alvo observado por dia, por fonte")
    ax.set_xlabel("dia (UTC)")
    ax.set_ylabel("termos")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _salvar_figura(fig, "alvo_h1_cobertura_por_dia.png")


def figura_series_dos_termos(alvo: pd.DataFrame, n_termos: int = 8) -> Path:
    """As séries do alvo unificado dos termos com mais dias: a primeira representação
    de "demanda observada por termo" do projeto."""
    perfil = perfil_das_series(alvo)
    escolhidos = perfil.head(n_termos)["termo"].tolist()
    fig, ax = plt.subplots(figsize=(10, 5))
    for termo in escolhidos:
        serie = alvo[alvo["termo"] == termo].sort_values("dia")
        ax.plot(serie["dia"], serie["alvo_unificado"], marker="o", label=termo)
    ax.set_title("Alvo unificado (percentil, 1 = topo) — termos com série mais longa")
    ax.set_xlabel("dia (UTC)")
    ax.set_ylabel("alvo unificado")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=7, ncol=2)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _salvar_figura(fig, "alvo_h1_series_por_termo.png")


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def construir_alvo(
    tabelas: dict[str, pd.DataFrame] | None = None,
    janela_comum: bool = False,
    com_mercado_livre: bool = False,
    com_regras_artes: bool = True,
) -> dict:
    """Roda o pipeline inteiro e devolve tudo num dict; usado pelo CLI e pelos testes.

    `com_regras_artes=True` é o estado desde 30/09 (regra definida em 29/09): a regra de
    "Artes e entretenimento" tira 38 itens da vitrine de instrumentos dos termos errados
    em que caíam. `False` reproduz o classificador anterior, o do experimento 1 e da
    reanálise; para o experimento 1 exato, junto de `com_mercado_livre=False`.

    `janela_comum=True` corta todas as fontes na primeira data em que todas observavam
    (o painel balanceado; ver `aplicar_janela_comum`). O padrão é `False`: guardar a
    série inteira e declarar a janela onde ela importa, em vez de descartar dado de
    forma permanente.

    Desde 20/10 o padrão é `com_mercado_livre=False`: o ML saiu do projeto (a fonte parou
    em 06/10; a análise, da Silver em diante, não o usa). `True` reproduz as medições
    datadas que o incluíam: o alvo de três fontes de 15/09 a 06/10, os pares do achado ⑤
    e a reanálise de 17/09; a série do ML chega cortada em 06/10
    (`carregar_bronze.PARADAS_DECLARADAS`). `False` também reproduz o experimento 1.
    """
    tabelas = tabelas if tabelas is not None else preparar_bronze(
        com_mercado_livre=com_mercado_livre)
    itens_sh = itens_dia_shopee(tabelas["tcc_bronze_shopee"], com_regras_artes)
    itens_am = itens_dia_amazon(tabelas["tcc_bronze_amazon"], com_regras_artes)

    # Regra 9 (15/09): o Mercado Livre entra como terceira fonte de alvo. Desde 23/09 a
    # posição e o percentil do ML vêm da Silver (`preparar_ml`), com os mesmos nomes e a
    # mesma fórmula da Amazon.
    itens_ml = None
    if com_mercado_livre and "tcc_bronze_ml" in tabelas:
        itens_ml = itens_dia_ml(tabelas["tcc_bronze_ml"], com_regras_artes)

    corte = None
    if janela_comum:
        # O painel balanceado corta todas as fontes, não duas: com o ML entrando em 15/07
        # e a Amazon em 16/07, cortar só Shopee e Amazon deixaria o alvo "balanceado"
        # começando um dia antes da data comum. Um painel que inclui um dia em que nem
        # todas observam não é balanceado (coberto por
        # `test_real_janela_comum_nao_muda_a_discordancia_entre_fontes`).
        if itens_ml is not None:
            (itens_sh, itens_am, itens_ml), corte = aplicar_janela_comum(
                itens_sh, itens_am, itens_ml
            )
        else:
            (itens_sh, itens_am), corte = aplicar_janela_comum(itens_sh, itens_am)
    alvo = alvo_por_termo_dia(itens_sh, itens_am, itens_ml)
    resultado = {
        "itens_shopee": itens_sh,
        "itens_amazon": itens_am,
        "itens_ml": itens_ml,
        "alvo": alvo,
        "janela_comum": corte,
        "cobertura_shopee": cobertura_do_join(itens_sh, "product_name"),
        "cobertura_amazon": cobertura_do_join(itens_am, "titulo"),
        # A que é vigiada por teste. A acumulada acima continua sendo reportada, porque
        # é ela que descreve o material da H1 na série inteira, mas não serve de piso
        # (ver `cobertura_do_join`).
        "cobertura_shopee_recente": cobertura_do_join(
            itens_sh, "product_name", dias=JANELA_COBERTURA_DIAS
        ),
        "cobertura_amazon_recente": cobertura_do_join(
            itens_am, "titulo", dias=JANELA_COBERTURA_DIAS
        ),
        "concordancia_categoria_amazon": concordancia_categoria_governada(itens_am),
        "perfil_series": perfil_das_series(alvo),
        "concordancia_fontes": concordancia_entre_fontes(alvo),
        "pool_intracategoria_shopee": pool_intracategoria_shopee(itens_sh),
        "mudanca_de_regime": mudanca_de_regime(alvo),
        # Desde 02/11 o Suggest não entra na Silver por padrão (a busca da H1 é o Trends, e
        # o casamento com ele está no `momentum_busca`). Esta medida só sai se a Silver vier
        # com o Suggest (`preparar_bronze(com_google_suggest=True)`); sem ele, `None`.
        "casamento_busca": (
            casamento_com_a_busca(alvo, tabelas["tcc_bronze_google_suggest"])
            if "tcc_bronze_google_suggest" in tabelas else None
        ),
        "_tabelas": tabelas,
    }
    # O ML recebe aqui as mesmas medidas da Amazon (23/09): cobertura do join, acumulada
    # e recente, e a conferência contra a categoria governada do carrossel.
    # Os três pares de concordância não entram por padrão: custam as permutações (~17 s
    # medidos em 22/09) e o `construir_alvo` tem muitos chamadores; quem precisa dos
    # pares chama `concordancia_todos_os_pares(resultado["alvo"])`, como faz o `_main`.
    if itens_ml is not None:
        resultado["cobertura_ml"] = cobertura_do_join(itens_ml, "titulo")
        resultado["cobertura_ml_recente"] = cobertura_do_join(
            itens_ml, "titulo", dias=JANELA_COBERTURA_DIAS
        )
        resultado["concordancia_categoria_ml"] = concordancia_categoria_governada(itens_ml)
    return resultado


def _main() -> None:
    resultado = construir_alvo()
    alvo = resultado["alvo"]

    print("=== 1. Join produto -> termo (classificador da Parte B3) ===")
    # As fontes saem do que o resultado tem, não de uma lista fixa.
    for fonte in [f for f in ("shopee", "amazon", "ml") if f"cobertura_{f}" in resultado]:
        c = resultado[f"cobertura_{fonte}"]
        r = resultado[f"cobertura_{fonte}_recente"]
        print(
            f"  {fonte:7s}: {c['com_termo']}/{c['itens_dia']} item-dia com termo "
            f"({c['cobertura']:.1%}) | sem titulo: {c['sem_titulo']} | "
            f"termos distintos: {c['termos_distintos']}"
        )
        # Os dois lado a lado de propósito: a diferença entre eles não é deterioração,
        # é a média acumulada arrastando julho para dentro do número corrente.
        print(
            f"           ultimos {JANELA_COBERTURA_DIAS} dias: "
            f"{r['com_termo']}/{r['itens_dia']} ({r['cobertura']:.1%})  "
            f"<- e este que tem piso; o acumulado acima converge para ele"
        )

    print("\n=== 2. Categoria do classificador x categoria governada do pool (Amazon e ML) ===")
    for fonte, pool in (("amazon", "vitrine"), ("ml", "carrossel")):
        conc = resultado.get(f"concordancia_categoria_{fonte}")
        if conc is None:
            continue
        print(f"  {fonte}: concordam em {conc['concordam']}/{conc['avaliados']} ({conc['taxa']:.1%})")
        print(f"  maiores discordâncias ({pool} -> termo):")
        print(conc["top_discordancias"].to_string())
    print("  (atencao: as duas taxas não se comparam de cara: o mapa do ML é mais grosso — "
          "10 carrosséis em 6 categorias, contra 22 vitrines em 14 na Amazon)")
    print("  (e no ML ela NÃO é validação independente: o mapa foi escolhido pela maioria "
          "deste mesmo classificador em 23/09 — é descrição, não prova)")

    print("\n=== 3. O alvo unificado ===")
    print(f"  linhas (termo-dia): {len(alvo)}")
    print(f"  termos distintos:   {alvo['termo'].nunique()}")
    print(f"  dias cobertos:      {alvo['dia'].nunique()} ({alvo['dia'].min()} a {alvo['dia'].max()})")
    print("  por composição de fontes:")
    print(alvo["fontes"].value_counts().to_string())

    print("\n=== 4. Perfil das séries por termo ===")
    perfil = resultado["perfil_series"]
    print(f"  termos em mais de uma fonte: {int(perfil['em_mais_de_uma_fonte'].sum())} de {len(perfil)}")
    print("  por nº de fontes: " + perfil["n_fontes"].value_counts().sort_index().to_dict().__str__())
    print(f"  dias por termo — mediana {perfil['dias'].median():.0f}, máximo {perfil['dias'].max()}")
    print(f"  termos com >= 5 dias: {int((perfil['dias'] >= 5).sum())}")
    print("  top 10 por comprimento de série:")
    print(perfil.head(10).to_string(index=False))

    print("\n=== 5. As fontes concordam? (sanidade do índice comum, NÃO é a H1) ===")
    # Todos os pares presentes, cada um contra o próprio nulo:
    for par, v in concordancia_todos_os_pares(alvo).items():
        if "termos" not in v:
            print(f"  {par}: só {v['pares']} termo-dia — sem IC")
            continue
        print(
            f"  {par}: rho por termo {v['spearman_por_termo']:+.4f} · IC95 {v['ic95']} · "
            f"{v['termos']} termos · z contra o próprio nulo {v['z_contra_o_proprio_nulo']:+.2f} · "
            f"p {v['p_empirico_bilateral']:.3f}"
        )
        confundidores = {k: round(x, 4) for k, x in v.items() if k.startswith("spearman_com_n_itens_")}
        print(f"      confundidor (percentil × nº de itens): {confundidores}")
    print("  por que o percentil da Shopee é por DIA e não por CATEGORIA:")
    for k, v in resultado["pool_intracategoria_shopee"].items():
        print(f"    {k}: {v}")

    print("\n=== 5b. A mudança de REGIME do alvo unificado (armadilha de série temporal) ===")
    regime = resultado["mudanca_de_regime"]
    print(f"  corte {regime['corte']} (entrada da Amazon) · {regime['termos_nos_dois_regimes']} termos nos dois regimes")
    print(f"  desvio-padrão do alvo_unificado: {regime['dp_unificado_antes']:.3f} -> {regime['dp_unificado_depois']:.3f}")
    print(f"  desvio-padrão do alvo_shopee (controle): {regime['dp_shopee_antes']:.3f} -> {regime['dp_shopee_depois']:.3f}")
    print(
        f"  fontes do painel: {' + '.join(regime['fontes_do_painel'])}\n"
        f"  depois do corte — mais de uma fonte: {regime['fracao_multifonte_depois']:.4f}"
        f" · uma só: {regime['fracao_uma_fonte_depois']:.4f}"
        f" · todas: {regime['fracao_todas_as_fontes_depois']:.4f}"
    )

    print("\n=== 6. Casamento com a série de busca do Suggest (até 02/11) ===")
    casamento = resultado["casamento_busca"] or {
        "fora_da_analise": "o Suggest saiu em 02/11; a busca da H1 é o Trends (momentum_busca)"
    }
    for k, v in casamento.items():
        if k == "termos_sem_serie_de_busca":
            print(f"  {k}: {len(v)} -> {v[:12]}{' ...' if len(v) > 12 else ''}")
        else:
            print(f"  {k}: {v}")

    PROCESSADO_DIR.mkdir(parents=True, exist_ok=True)
    alvo.to_csv(SAIDA_TERMO_DIA, index=False, encoding="utf-8")
    # O CSV item-dia inclui o ML quando ele está presente.
    fontes_item_dia = [
        resultado["itens_shopee"].assign(fonte="shopee"),
        resultado["itens_amazon"].assign(fonte="amazon"),
    ]
    if resultado.get("itens_ml") is not None:
        fontes_item_dia.append(resultado["itens_ml"].assign(fonte="ml"))
    itens = pd.concat(fontes_item_dia, ignore_index=True)
    itens.to_csv(SAIDA_ITEM_DIA, index=False, encoding="utf-8")

    # --- o painel balanceado, como artefato próprio (não substitui o de série cheia) ---
    balanceado = construir_alvo(resultado["_tabelas"], janela_comum=True)
    alvo_b = balanceado["alvo"]
    print("\n=== 7. O painel BALANCEADO (todas as fontes a partir da data comum) ===")
    print(f"  data mínima comum: {balanceado['janela_comum']}")
    print(f"  linhas: {len(alvo_b)} (contra {len(alvo)} na série cheia)")
    print(f"  termos: {alvo_b['termo'].nunique()} · dias: {alvo_b['dia'].nunique()}")
    print("  por composição de fontes:")
    print(alvo_b["fontes"].value_counts().to_string())
    for a, b in PARES_DE_FONTES:
        if f"alvo_{a}" not in alvo_b.columns or f"alvo_{b}" not in alvo_b.columns:
            continue   # sem o ML (padrão desde 20/10), só o par Shopee × Amazon
        conc_b = concordancia_entre_fontes(alvo_b, a, b)
        print(f"  correlação {a} x {b} no painel balanceado: {conc_b.get('spearman_por_termo')}")
    print(f"  mudança de regime: {balanceado['mudanca_de_regime'].get('nao_aplicavel') and 'NÃO SE APLICA (é o efeito do corte: não existe "antes")' or balanceado['mudanca_de_regime']}")
    print("  custo do corte, medido:")
    # Todas as fontes presentes entram aqui (regra 9): o corte também atinge o ML, e o
    # relatório tem de declarar esse custo.
    fontes_do_corte = [
        ("shopee", resultado["itens_shopee"], balanceado["itens_shopee"]),
        ("amazon", resultado["itens_amazon"], balanceado["itens_amazon"]),
    ]
    if resultado.get("itens_ml") is not None and balanceado.get("itens_ml") is not None:
        fontes_do_corte.append(("ml", resultado["itens_ml"], balanceado["itens_ml"]))
    for nome, cheio, cortado in fontes_do_corte:
        perdidos = len(cheio) - len(cortado)
        dias = cheio["dia"].nunique() - cortado["dia"].nunique()
        print(f"    {nome}: perde {perdidos} de {len(cheio)} item-dia ({perdidos/len(cheio):.1%}) e {dias} dias")

    alvo_b.to_csv(SAIDA_TERMO_DIA_BALANCEADO, index=False, encoding="utf-8")

    caminhos = [figura_cobertura_por_dia(alvo), figura_series_dos_termos(alvo)]
    print("\n=== Saídas ===")
    print(f"  {SAIDA_TERMO_DIA} ({len(alvo)} linhas — série cheia)")
    print(f"  {SAIDA_TERMO_DIA_BALANCEADO} ({len(alvo_b)} linhas — painel balanceado)")
    print(f"  {SAIDA_ITEM_DIA} ({len(itens)} linhas)")
    for c in caminhos:
        print(f"  {c}")


if __name__ == "__main__":
    _main()
