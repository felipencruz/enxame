# -*- coding: utf-8 -*-
"""Bronze -> Silver: as transformações declaradas na especificação da camada Silver.

Cada função abaixo implementa um tratamento documentado, com a numeração da
especificação: §3.2 (as "sujeiras") e §2 (dedup da Amazon). Nenhuma regra nova é
decidida aqui; este módulo é a implementação de um desenho já fechado.

Escopo desta versão (deliberado):
- Os 7 itens do §3.2 (linhas de erro, \\xa0 no preço, rank/avaliação da Amazon, o filtro
  do YouTube pré-`coletar_youtube`, o dedup de paginação da Shopee, o `item_id` nulo da
  Amazon) e a regra de dedup do §2 (pior rank vence).
- O item 4 (§3.2, agregar buzz por dia) é uma função separada
  (`agregar_youtube_por_dia`), porque muda a granularidade (o Bronze é por rodada, e a
  Silver aqui continua por rodada); misturar as duas quebraria a rastreabilidade
  snapshot a snapshot que o Bronze existe para preservar.
- A agregação "um ponto por dia" do `sales` da Shopee (§3.1) não está implementada aqui:
  é específica do teste da H1 (em 17/07 optou-se por fazer a EDA descritiva antes da H1).
  Essa agregação entra como parte do teste da H1, não da Silver geral; `preparar_shopee`
  aqui só resolve a duplicata de paginação (item 7).
- Desde 23/09 o ML recebe o mesmo tratamento da Amazon (posição -> `rank`,
  `rank_percentil`, `categoria_parte_a`, dedup): ver `preparar_ml`.
- Fora dos 7 itens documentados: o Bronze da Amazon ainda guarda as 4 rodadas da rota
  geral aposentada em 15/07 (36 linhas cada, sem `preco`, categorias como "Mais Vendidos
  em Cozinha" que não casam com o mapa de 22 vitrines). `preparar_amazon` as descarta
  (ver comentário na função): são linhas reais, não erro, e por isso não se enquadram
  em nenhum dos 7 itens.

O Bronze nunca é alterado. Cada função recebe um DataFrame (do `carregar_bronze`) e
devolve outro, sem tocar o CSV de origem.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from amazon_vitrines_inventario import VITRINES  # noqa: E402
from carregar_bronze import carregar_tabela  # noqa: E402

PROCESSADO_DIR = Path(__file__).resolve().parent.parent / "02_Dados" / "processado"

# Tabela `tcc_amazon_vitrines`, materializada em amazon_vitrines_inventario.VITRINES:
# rótulo que a Amazon exibe (== Bronze.categoria_pagina) -> categoria da Parte A.
# Só as 22 em escopo entram aqui; as 6 fora de escopo nunca aparecem como categoria_pagina
# (não coletamos essas vitrines), e os rótulos da rota geral aposentada ("Mais Vendidos
# em X") ficam de fora de propósito (ver a docstring do módulo).
_MAPA_VITRINE_CATEGORIA = {
    rotulo: categoria
    for _slug, (rotulo, categoria, _motivo) in VITRINES.items()
    if categoria is not None
}

# Rótulos que sabemos descartar e por quê. Serve para o aviso de `preparar_amazon`
# distinguir "descarte esperado" de "a Amazon mudou o nome de uma vitrine".
_ROTULOS_FORA_DE_ESCOPO = {
    rotulo for _slug, (rotulo, categoria, _motivo) in VITRINES.items() if categoria is None
}
_PREFIXO_ROTA_GERAL = "Mais Vendidos em "  # a rota aposentada em 15/07

# Carrossel do Mercado Livre -> categoria da Parte A: o equivalente, para o ML, do mapa
# acima (23/09). Com o percentil do ML, a fonte passou a receber o mesmo tratamento da
# Amazon em todas as etapas. A Amazon sempre teve este mapa (`tcc_amazon_vitrines`) e o ML
# não; sem ele, a conferência "classificador × categoria governada" e a dedup por
# categoria existiam para uma fonte só.
# Critério de atribuição (23/09): a categoria em que se encaixam melhor, medida. Para cada
# carrossel, a categoria em que caem os produtos que ele de fato serve (classificador da
# Parte B3 sobre os títulos, produto distinto por carrossel). Nove seguem a maioria com
# folga (Games 100% Eletrônicos · Eletrodomésticos 97% Casa e jardim · Calçados 84%
# Vestuário · Informática 72% Eletrônicos ...).
# `Esportes e Fitness` não vai para Artigos esportivos, apesar do nome: dos 686
# produtos, 329 são whey, 88 suplemento, 49 creatina, 35 ômega 3, 32 pré-treino; 84% caem
# em Saúde e beleza e 3% em Artigos esportivos. O projeto já classifica whey e creatina
# como Saúde e beleza (regra da Parte B2, 15/07). Com essa escolha, a conferência do
# classificador no ML vai de 75,1% para 88,3%; o alvo e a dedup não mudam (nenhuma das 525
# colisões envolve esse carrossel). Seguir o nome do carrossel, por analogia com a Amazon,
# erraria exatamente neste caso.
_MAPA_CARROSSEL_ML_CATEGORIA = {
    "Acessórios para Veículos": "Veículos e peças",
    "Beleza e Cuidado Pessoal": "Saúde e beleza",
    "Calçados, Roupas e Bolsas": "Vestuário e acessórios",
    "Celulares e Telefones": "Eletrônicos",
    "Eletrodomésticos": "Casa e jardim",
    "Eletrônicos, Áudio e Vídeo": "Eletrônicos",
    "Esportes e Fitness": "Saúde e beleza",  # suplementos: ver o bloco acima
    "Ferramentas": "Ferragens",
    "Games": "Eletrônicos",
    "Informática": "Eletrônicos",
}

_PADRAO_AVALIACAO = re.compile(r"^(\d+,\d+) de 5 estrelas, ([\d.]+) classifica")
_PADRAO_RANK = re.compile(r"^#(\d+)$")


def _preco_para_float(serie: pd.Series) -> pd.Series:
    """'R$\\xa0432,22' ou 'R$ 150' -> 432.22 / 150.0.

    Medido em 17/07 contra o Bronze vivo: só a Amazon grava `\\xa0` (espaço não-quebrável);
    o ML grava espaço comum. A limpeza abaixo trata os dois formatos (§3.2 item 1), sem
    custo quando `\\xa0` não aparece.
    """
    limpo = (
        serie.astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.replace("R$", "", regex=False)
        .str.strip()
        .str.replace(".", "", regex=False)  # separador de milhar (padrão BR)
        .str.replace(",", ".", regex=False)  # separador decimal (padrão BR)
    )
    # .astype(float) é necessário além do to_numeric: quando nenhum preço da coluna tem
    # centavos (caso do ML até a receita v3: "R$ 1.099", sem ",00"), to_numeric infere
    # int64 em vez de float64, e um preço com tipo que muda de rodada para rodada é frágil.
    # A ausência de centavos no ML era do coletor, não da fonte: a receita lia só o
    # `<span>` e deixava os centavos no `<sup>`. Desde a v4 (26/09) eles vêm; ver
    # `INICIO_PRECO_COM_CENTAVOS_ML` e a coluna `preco_regime`.
    return pd.to_numeric(limpo, errors="coerce").astype(float)


# Mudança de regime do preço do ML (29/09/2026): os centavos são mantidos e a mudança é
# declarada. Até a receita v3 o preço do ML era gravado sem centavos (o seletor lia só o
# `<span>` do layout antigo; os centavos ficavam num `<sup>`), em toda a série desde 13/07.
# A v4, no ar desde 25/09 ~18:05 BRT, lê o preço inteiro, e a primeira rodada agendada com
# ela é a de 26/09 00:00 BRT (03:00 UTC). Medido no export de 29/09: zero vírgulas antes
# deste instante, 1.691 de 2.168 preços com vírgula depois, zero nulos nos dois lados, e nos
# 180 itens presentes nos dois regimes a razão preço_novo/preço_antigo tem mediana 1,00
# (nada lido 100× maior). O degrau é de até R$ 0,99 por preço, para cima, e é sistemático;
# por isso é declarado numa coluna, em vez de truncar o dado novo para esconder o antigo.
INICIO_PRECO_COM_CENTAVOS_ML = pd.Timestamp("2026-09-26T03:00:00Z")


def _regime_do_preco_ml(df: pd.DataFrame) -> pd.Series:
    """'sem_centavos' antes da v4, 'com_centavos' depois, pela data da coleta.

    Fail-closed: preço com vírgula antes do corte significa que a premissa caiu (a série
    antiga não tinha como trazer centavos), e seguir em silêncio rotularia errado.
    """
    quando = pd.to_datetime(df["coletado_em"], utc=True)
    depois = quando >= INICIO_PRECO_COM_CENTAVOS_ML
    virgula_antes = df["preco"].astype(str).str.contains(",", regex=False) & ~depois
    if virgula_antes.any():
        raise ValueError(
            f"[preparar_silver] {int(virgula_antes.sum())} preço(s) do ML com centavos ANTES de "
            f"{INICIO_PRECO_COM_CENTAVOS_ML} — a premissa dessa data caiu (a receita antiga não "
            f"lia centavos). Conferir a receita da rodada antes de rotular o regime."
        )
    return pd.Series(["com_centavos" if d else "sem_centavos" for d in depois], index=df.index, dtype="object")


def preparar_google_suggest(df: pd.DataFrame) -> pd.DataFrame:
    """§3.2 item 5: remove a linha de erro (`fonte == 'google_suggest_erro'`)."""
    out = df[df["fonte"] != "google_suggest_erro"]
    return out.reset_index(drop=True)


def preparar_youtube(df: pd.DataFrame) -> pd.DataFrame:
    """§3.2 itens 3 e 5.

    Item 3: remove as rodadas de 09-10/07 (pré-`coletar_youtube`, quando o coletor
    ainda media as 16 categorias amplas da Parte A em vez dos termos de produto;
    medido em 17/07: são exatamente os dois primeiros dias, 16 termos/dia).
    Item 5: remove a linha de erro (`titulo` começa com `[ERRO]`, `video_id` nulo).
    """
    out = df.copy()
    out["coletado_em"] = pd.to_datetime(out["coletado_em"])
    out = out[out["coletado_em"] >= pd.Timestamp("2026-07-11", tz="UTC")]
    out = out[~out["titulo"].astype(str).str.startswith("[ERRO]")]
    return out.reset_index(drop=True)


def agregar_youtube_por_dia(df_limpo: pd.DataFrame) -> pd.DataFrame:
    """§3.2 item 4: agrega buzz por dia, não por rodada.

    A frequência do coletor mudou de 2x/dia para 1x/dia em 15/07 (Parte B2, o slot
    A/B); somar rodadas sem agregar por dia compararia regimes diferentes. Recebe a
    saída de `preparar_youtube` (já sem as rodadas de 09-10/07 e sem erro).
    """
    out = df_limpo.copy()
    out["dia"] = out["coletado_em"].dt.date
    agregado = (
        out.groupby(["termo_semente", "dia"])
        .agg(
            total_results_max=("total_results", lambda s: pd.to_numeric(s, errors="coerce").max()),
            videos_distintos=("video_id", "nunique"),
        )
        .reset_index()
    )
    return agregado


def preparar_shopee(df: pd.DataFrame) -> pd.DataFrame:
    """§3.2 item 7: a API não pagina; as 5 páginas de cada rodada devolvem o mesmo
    conteúdo, medido em 16/07 (sonda) e confirmado em 17/07 contra o Bronze vivo. A
    contagem de repetição não é sempre exatamente 5x por item (varia por rodada), mas
    o dedup abaixo é seguro de qualquer forma: colapsa só o que é de fato o mesmo
    `item_id` na mesma rodada.

    `price` e `sales` já chegam numéricos do coletor (`parseFloat`/`Number`, não string
    crua como no ML/Amazon); nenhum parse adicional aqui.
    """
    out = df.drop_duplicates(subset=["item_id", "coletado_em"], keep="first").copy()
    for col in ("price", "sales", "rating_star", "price_discount_rate", "commission_rate"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.reset_index(drop=True)


def posicao_no_carrossel_ml(df: pd.DataFrame, falhar_se_partido: bool = True) -> pd.DataFrame:
    """A posição de cada item no carrossel do ML, derivada da ordem de inserção (`id`).

    Até 24/09 o Bronze do ML não tinha coluna de posição (desde a publicação do coletor
    novo ele grava `rank`; ver `_preferir_rank_gravado`, que usa esta derivação como
    controle), mas a fonte serve a ordem e o coletor a preservou: o `id` da data table é
    insert-only e, dentro de cada rodada, cada carrossel é um bloco contíguo (provado
    contra o HTML bruto de 29/07 em `ordem_carrossel_ml.py`). Esta é a única derivação da
    posição no projeto: `ordem_carrossel_ml.bronze_com_posicao` a chama em vez de
    repeti-la, para que a regra tenha uma única implementação.

    Devolve `df` com `rank` (1 = topo) e `n_carrossel` nas linhas que têm
    `categoria_pagina`; as rodadas anteriores a 15/07 gravam categoria nula, e sem
    carrossel não há posição: elas ficam com `rank` nulo, declaradas, não descartadas.

    Fail-closed: se um carrossel aparecer partido em mais de um bloco dentro da rodada,
    o `cumcount` contaria itens de outro carrossel. Isso levanta exceção em vez de
    produzir uma posição errada com aparência de certa. `falhar_se_partido=False` existe
    só para o instrumento de diagnóstico (`ordem_carrossel_ml.bronze_com_posicao`), que
    conta as rodadas partidas em vez de parar nelas.
    """
    if "id" not in df.columns:
        raise ValueError(
            "o Bronze do ML chegou sem a coluna `id` — é a ordem de inserção que dá a posição "
            "no carrossel, e sem ela não há percentil. Carregue pelo `carregar_bronze`."
        )
    gravado = df["rank"] if "rank" in df.columns else pd.Series(pd.NA, index=df.index, dtype="object")
    out = df.copy()
    out["id"] = pd.to_numeric(out["id"], errors="coerce")
    out = out.sort_values("id", kind="stable")
    com_cat = out["categoria_pagina"].notna()
    blocos = out[com_cat]
    for rodada, g in (blocos.groupby("coletado_em", sort=False) if falhar_se_partido else ()):
        marca = (g["categoria_pagina"] != g["categoria_pagina"].shift()).cumsum()
        if marca.nunique() != g["categoria_pagina"].nunique():
            raise ValueError(
                f"rodada {rodada} do ML tem carrossel partido em mais de um bloco de `id` — "
                "a posição derivada da ordem de inserção deixaria de ser a do carrossel."
            )
    grupo = ["coletado_em", "categoria_pagina"]
    out["rank"] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    out.loc[com_cat, "rank"] = (blocos.groupby(grupo, sort=False).cumcount() + 1).astype("Int64")
    out["n_carrossel"] = out.groupby(grupo)["rank"].transform("count").astype("Int64")
    out.loc[~com_cat, "n_carrossel"] = pd.NA
    return _preferir_rank_gravado(out, gravado.reindex(out.index))


_RANK_GRAVADO_ML = r"^\s*(\d+)\s+de\s+(\d+)\s*$"


def _preferir_rank_gravado(out: pd.DataFrame, gravado: pd.Series) -> pd.DataFrame:
    """Desde a publicação do coletor novo (24/09), o Bronze do ML grava a posição na
    coluna `rank`, no formato `"k de M"` do `aria-label` da fonte, numerada pelo n8n na
    ordem da resposta (ver o nó `Achatar Produtos` do coletor `5vSP1WtLKpTTVBn6`). Onde ela
    existe, é ela que vale; a derivação pela ordem de inserção vira controle positivo.

    Fail-closed nos dois sentidos: valor gravado fora do padrão, ou posição/tamanho
    gravados que divergem da derivação, levantam exceção. As duas vêm da mesma ordem por
    caminhos diferentes (a da resposta e a do `id`); se discordarem, uma premissa caiu, e
    escolher uma delas em silêncio esconderia qual. A coluna `rank_origem` diz, linha a
    linha, de onde veio a posição; as rodadas anteriores à publicação ficam `derivado`.
    """
    out["rank_origem"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out.loc[out["rank"].notna(), "rank_origem"] = "derivado"
    tem = gravado.notna() & (gravado.astype(str).str.strip() != "")
    if not tem.any():
        return out
    partes = gravado[tem].astype(str).str.extract(_RANK_GRAVADO_ML)
    if partes[0].isna().any():
        amostra = gravado[tem][partes[0].isna()].head(3).tolist()
        raise ValueError(f"`rank` gravado do ML fora do padrão 'k de M': {amostra}")
    k = partes[0].astype(int)
    m = partes[1].astype(int)
    derivado_k = out.loc[tem, "rank"]
    derivado_m = out.loc[tem, "n_carrossel"]
    diverge = derivado_k.isna() | (derivado_k.astype("Int64") != k) | (derivado_m.astype("Int64") != m)
    if diverge.any():
        linhas = out.loc[tem][diverge.to_numpy()][["id", "coletado_em", "categoria_pagina", "rank", "n_carrossel"]]
        raise ValueError(
            f"{int(diverge.sum())} linha(s) do ML com `rank` gravado que DIVERGE da posição "
            f"derivada da ordem de inserção — a ordem da resposta e a do `id` deixaram de ser a "
            f"mesma. Amostra:\n{linhas.head(5).to_string()}"
        )
    out.loc[tem, "rank"] = k.astype("Int64").to_numpy()
    out.loc[tem, "rank_origem"] = "gravado"
    return out


def preparar_ml(df: pd.DataFrame) -> pd.DataFrame:
    """§3.2 itens 1 e 5 e, desde 23/09, o mesmo tratamento que a Amazon recebe.

    1. Remove a linha de erro (`titulo` [ERRO] / `item_id` nulo).
    2. Parseia `preco`/`preco_antigo` para numérico.
    3. Posição e percentil, com os mesmos nomes de coluna da Amazon (`rank`,
       `rank_percentil`): posição derivada da ordem de inserção
       (`posicao_no_carrossel_ml`) e a fórmula do §2.5, `1 - (rank-1)/(n-1)`, com o N
       observado em cada (`categoria_pagina`, `coletado_em`), calculado antes da
       dedup, pelo mesmo motivo do passo 6 da Amazon.
    4. `categoria_parte_a` pelo mapa governado do carrossel.
    5. Dedup por (`item_id`, `categoria_parte_a`, `coletado_em`), com
       `n_carrosseis_publicando` guardando quantos carrosséis o publicavam.

    Motivo (23/09): com o percentil, o ML passou a ter medida de posição comparável à da
    Amazon e deve receber o mesmo tratamento em todas as etapas. Calcular o percentil do
    ML fora da Silver, só dentro do alvo, faria todo consumidor da Silver ver a Amazon com
    percentil e o ML sem.

    A dedup não copia a regra literal da Amazon, e a diferença foi medida (23/09).
    A Amazon mantém o pior rank porque toda vitrine tem 50 itens: ali pior rank e pior
    percentil são a mesma linha. Os carrosséis do ML têm 5 a 20 itens (medido em 24/09),
    e em 46 das 525 colisões da série as duas regras escolhem linhas diferentes. O que se
    preserva é o princípio (fail-closed: na dúvida, a leitura que não infla), então aqui
    sobrevive o pior percentil, que é também o que o `alvo_h1` faz por item-dia nas duas
    fontes. Uma regra validada numa fonte precisa ser medida também na outra.
    As colisões vêm quase todas de carrosséis que caem na mesma categoria da Parte A
    (Celulares × Eletrônicos × Informática × Games, todos Eletrônicos); o preço diverge
    em 5 das 525.

    Linhas das rodadas anteriores a 15/07 (sem `categoria_pagina`) ficam, com `rank`,
    `rank_percentil` e `categoria_parte_a` nulos: servem ao preço, não ao alvo.

    Os passos 1 a 4 ficam em `ml_ate_o_percentil`: o `auditar_comparabilidade_vitrines`
    precisa deles sem a dedup, e reescrevê-los lá criaria uma segunda cópia da fórmula.
    """
    out = ml_ate_o_percentil(df)

    grupo = ["item_id", "categoria_parte_a", "coletado_em"]
    com_categoria = out["categoria_parte_a"].notna()
    governadas = out[com_categoria].copy()
    governadas["n_carrosseis_publicando"] = governadas.groupby(grupo)["item_id"].transform("size")
    governadas = governadas.sort_values(["rank_percentil", "rank"], ascending=[True, False]).drop_duplicates(
        subset=grupo, keep="first"
    )
    resto = out[~com_categoria].copy()
    resto["n_carrosseis_publicando"] = pd.NA
    out = pd.concat([governadas, resto])
    out["n_carrosseis_publicando"] = out["n_carrosseis_publicando"].astype("Int64")
    return out.sort_values("id", kind="stable").reset_index(drop=True)


def ml_ate_o_percentil(df: pd.DataFrame) -> pd.DataFrame:
    """Passos 1 a 4 do `preparar_ml`: tudo até o `rank_percentil` e a `categoria_parte_a`,
    sem a dedup. É o equivalente do `auditar_comparabilidade_vitrines.preparar_ate_o_percentil`
    da Amazon, e existe como função para que a fórmula tenha uma única implementação."""
    out = df[df["item_id"].notna() & ~df["titulo"].astype(str).str.startswith("[ERRO]")].copy()
    out["preco_regime"] = _regime_do_preco_ml(out)  # antes do parse: a trava lê o texto cru
    out["preco"] = _preco_para_float(out["preco"])
    out["preco_antigo"] = _preco_para_float(out["preco_antigo"])

    out = posicao_no_carrossel_ml(out)
    n = out["n_carrossel"].astype(float)
    percentil = 1 - (out["rank"].astype(float) - 1) / (n - 1).clip(lower=1)
    out["rank_percentil"] = percentil.where(n > 1, 1.0).where(out["rank"].notna())

    out["categoria_parte_a"] = out["categoria_pagina"].map(_MAPA_CARROSSEL_ML_CATEGORIA)
    desconhecidos = sorted(
        set(out.loc[out["categoria_pagina"].notna() & out["categoria_parte_a"].isna(), "categoria_pagina"])
    )
    if desconhecidos:
        # Mesma postura do `_avisar_vitrines_desconhecidas` da Amazon: carrossel novo não
        # derruba a Silver, mas não passa calado. A linha fica (tem posição e percentil);
        # o que ela perde é a categoria governada e, com isso, a dedup.
        print(
            f"[preparar_silver] AVISO: carrossel(is) do ML sem categoria da Parte A: "
            f"{desconhecidos}. Se o ML criou ou renomeou um carrossel, atualizar "
            f"_MAPA_CARROSSEL_ML_CATEGORIA em 03_Analise/preparar_silver.py.",
            file=sys.stderr,
        )
    return out


def _avisar_vitrines_desconhecidas(df: pd.DataFrame) -> list[str]:
    """Avisa quando aparece um `categoria_pagina` que nenhuma regra sabe descartar.

    Por que existe (30/07/2026). O filtro de `preparar_amazon` é uma lista branca de 22
    rótulos escritos à mão. Se a Amazon renomear uma vitrine ("Cozinha" -> "Cozinha e
    Mesa"), todas as linhas dela somem da Silver sem aviso (50 itens por rodada), e nada
    detecta: o `auditar_volume_coleta.py` aplica o mesmo filtro, e o painel
    `[util] Status das Coletas` continuaria vendo 22 categorias distintas. A fonte já
    trocou de rota uma vez, em 15/07.

    Não levanta exceção de propósito: os dois descartes conhecidos (as 6 vitrines fora de
    escopo e a rota geral aposentada) são legítimos e frequentes, e transformar isso em
    erro quebraria a Silver com dado que já está no Bronze. O objetivo é que um rótulo
    inesperado não passe despercebido.
    """
    rotulos = set(df["categoria_pagina"].dropna().unique())
    desconhecidos = sorted(
        r
        for r in rotulos - set(_MAPA_VITRINE_CATEGORIA) - _ROTULOS_FORA_DE_ESCOPO
        if not r.startswith(_PREFIXO_ROTA_GERAL)
    )
    if desconhecidos:
        linhas = int(df["categoria_pagina"].isin(desconhecidos).sum())
        print(
            f"[preparar_silver] AVISO: {len(desconhecidos)} rótulo(s) de vitrine "
            f"desconhecido(s) no Bronze da Amazon, {linhas} linha(s) serão DESCARTADAS: "
            f"{desconhecidos}. Se a Amazon renomeou uma vitrine, atualizar VITRINES em "
            f"03_Analise/amazon_vitrines_inventario.py.",
            file=sys.stderr,
        )
    return desconhecidos


def linhas_legitimas_amazon(df: pd.DataFrame, avisar: bool = True) -> pd.DataFrame:
    """O denominador de tudo que se afirma sobre a Amazon: passos 1 e 2 do
    `preparar_amazon`, extraídos em 28/08 para terem uma única implementação.

    São as linhas que descrevem um produto servido pela rota atual: `item_id` não
    nulo, `titulo` sem `[ERRO]`, e `categoria_pagina` dentro das 22 vitrines. Ficam de
    fora a linha de erro (§3.2 itens 5 e 6) e as 4 rodadas da rota geral aposentada
    em 15/07 (§2.4.1).

    Por que é uma função: as taxas de dedup e de sobreposição da Amazon dependem deste
    recorte, e enquanto ele existia só dentro de `preparar_amazon` cada remedição o
    reconstruía. Em 28/08, três remedições deram 2,03%, 0,77% e 1,87% para a mesma
    dedup, todas corretas sobre denominadores diferentes. Fato com método declarado
    exige também denominador declarado.
    """
    out = df[df["item_id"].notna() & ~df["titulo"].astype(str).str.startswith("[ERRO]")].copy()
    if avisar:
        _avisar_vitrines_desconhecidas(out)
    return out[out["categoria_pagina"].isin(_MAPA_VITRINE_CATEGORIA)].copy()


def medir_dedup_e_sobreposicao_amazon(df: pd.DataFrame) -> dict[str, float]:
    """Reproduz as taxas de dedup e de sobreposição da Amazon, para que remedi-las
    seja executar, e não reconstruir (28/08).

    Devolve os dois pares sobre a mesma base (`linhas_legitimas_amazon`):

    - dedup: linhas que o `drop_duplicates` do passo 7 remove, sobre o total de
      linhas legítimas. Só colapsa colisão dentro da mesma `categoria_parte_a`.
    - sobreposição: pares (`item_id`, `coletado_em`) que aparecem em mais de uma
      vitrine, sobre o total de pares distintos. Conta item em duas vitrines
      quaisquer, inclusive de categorias diferentes, que a dedup não toca (§2.4).

    Invariante: a sobreposição é sempre maior que a dedup, e a diferença é
    exatamente a colisão entre categorias distintas. São fatos distintos e não devem
    ser confundidos.

    O denominador da sobreposição usa as linhas legítimas dos dois lados (28/08). Contar
    os pares antes do filtro da lista branca incluiria as 144 linhas da rota geral
    aposentada no denominador sem que pudessem entrar no numerador: no corte de 26/08,
    87.237 pares em vez de 87.093, e a taxa seria 2,461% em vez de 2,465% (0,004 pp,
    invisível na casa decimal publicada). O valor corrente é produzido pela função, e
    esta docstring não o copia.
    """
    legitimas = linhas_legitimas_amazon(df, avisar=False)
    n_legitimas = len(legitimas)

    vitrines_por_par = legitimas.groupby(["item_id", "coletado_em"])["categoria_pagina"].nunique()
    n_pares = len(vitrines_por_par)
    n_sobrepostos = int((vitrines_por_par > 1).sum())

    removidas = n_legitimas - len(preparar_amazon(df))

    return {
        "linhas_legitimas": n_legitimas,
        "dedup_removidas": removidas,
        "dedup_taxa": removidas / n_legitimas if n_legitimas else float("nan"),
        "pares_item_rodada": n_pares,
        "pares_em_mais_de_uma_vitrine": n_sobrepostos,
        "sobreposicao_taxa": n_sobrepostos / n_pares if n_pares else float("nan"),
    }


def preparar_amazon(df: pd.DataFrame, backfill_titulo: bool = False) -> pd.DataFrame:
    """§2.3 (pré-filtro + dedup), §2.5 (rank -> percentil) e §3.2 itens 1, 2, 5, 6.

    Ordem (importa: o percentil tem que vir antes do dedup, ver item 6 abaixo).
    Os passos 1 e 2 ficam em `linhas_legitimas_amazon` desde 28/08: eles são o
    denominador das taxas da Amazon e precisavam de uma única implementação.
    1. Pré-filtro (§2.3): remove `item_id` nulo e `titulo` [ERRO]; cobre os itens 5 e 6
       do §3.2 (a linha de erro e a linha legítima cujo link não casou o ASIN, que
       gravam ambas `item_id: null`).
    2. Fora dos 7 itens documentados (17/07): remove as linhas da rota geral aposentada
       em 15/07, que ficam no Bronze (36/rodada, sem `preco`, categorias como "Mais
       Vendidos em Cozinha") mas não casam com as 22 vitrines da rota atual.
       Filtrar por `categoria_pagina not in mapa` é mais robusto que filtrar por data:
       funciona mesmo que uma rodada antiga apareça fora de ordem.
    3. Mapeia `categoria_pagina` -> `categoria_parte_a` (tabela `tcc_amazon_vitrines`).
    4. Parseia `rank` ("#36" -> 36) e `avaliacao` ("4,8 de 5 estrelas, 3.671
       classificações" -> `nota`=4.8, `n_avaliacoes`=3671): item 2.
    5. Parseia `preco` (`R$\\xa0432,22` -> 432.22): item 1.
    6. §2.5, rank -> percentil dentro da vitrine: `rank_percentil` (1.0 = melhor,
       0.0 = pior), com o N observado em cada (`categoria_pagina`, `coletado_em`) como
       denominador, não 50 fixo (rodadas degradadas, ex. `office` com 1 item, existem;
       ver §2.1). Calculado antes do dedup, de propósito: o dedup do passo 7 remove
       de uma vitrine os itens que "perderam" para outra vitrine com rank pior; isso
       encolhe o N pós-dedup da vitrine sem encolher os ranks nela restantes, e um
       `#48` numa vitrine que só sobrou com 20 linhas pós-dedup viraria percentil
       negativo. Calculando antes, o percentil reflete o tamanho real da vitrine como
       raspada, e sobrevive ao dedup junto com a linha vencedora (testado: sem isto,
       `test_amazon_percentil_real_esta_no_intervalo_0_1` falha com 64 percentis < 0).
    7. Dedup por (`item_id`, `categoria_parte_a`, `coletado_em`): mantém o pior rank
       (o número maior), regra medida no §2.2 (26/26 duplicatas concordam em
       preço/título/avaliação; a vitrine estreita dá o rank melhor em 21/21 colisões).

    8. §3.2 item 8 (12/08): backfill do `titulo`, `backfill_titulo=True`. Opcional
       e desligado por padrão, porque é não causal (ver o bloco abaixo). A linha
       nunca foi descartada (rank, categoria e preço são válidos); o backfill apenas
       recupera o título do mesmo ASIN quando ele existe em outra data.

    `titulo` nulo em linha legítima: observado em 17/07, regra definida em 12/08.
    A linha tem `item_id` válido e sem marca `[ERRO]`, mas `titulo` nulo: não é a
    linha de erro do item 5/6 (essa tem `item_id` nulo também). Causa raiz no
    §3.2.1 (o seletor fixava `line-clamp-3`), corrigida em produção em 23/07: o
    último título nulo da série é de 23/07 03:00 UTC.

    Medido em 12/08 sobre a série 15/07 a 12/08 (59.893 linhas legítimas): 1.018 nulos,
    1,70%. O defeito não se restringe a Games e Consoles: atingiu 18 vitrines (Games
    82,4%, Esporte 9,47%, Brinquedos 9,33%, Moda 5,33% e mais 14 abaixo de 4%). Mesma
    causa, frequências diferentes.

    Por que o backfill é seguro, e o número que o autoriza: o ASIN persiste entre
    rodadas, então o título de outra observação do mesmo item recupera a linha. Dos
    156 ASINs com título nulo antes de 23/07, 120 (76,9%) têm título em outra data,
    o que recupera 819 de 960 linhas (85,3%); e 119 desses 120 (99,2%) têm um único
    título em toda a série. Por isso o critério "primeiro título observado" é
    indiferente na prática, e fica declarado.

    Por que o padrão é `False`, o ponto principal deste bloco: o backfill é não causal.
    Os nulos são de 16 a 22/07 e os títulos só passam a existir em 23/07; logo todo
    preenchimento traz informação do futuro para a linha do passado. Não há versão
    causal útil: preencher só com o passado não recupera nada, porque no início da
    janela não havia título nenhum. A limitação é do reparo, não da implementação.

    O custo, medido em 12/08: ligado por padrão, o backfill mudou a reprodução da
    decisão de 22/07 da régua do buzz de 47/30/48 para 46/29/49. O título alimenta o
    classificador, que atribui termo ao item, o que muda a contagem por termo. A
    diferença foi detectada pela trava de reprodução, rodando com a série truncada
    naquele dia. Uma regra validada só no alvo que a motivou não está validada nos
    demais: a EDA descritiva é retrospectiva e não é afetada; a H1 é um teste de
    lead-lag e é.

    Use `backfill_titulo=True` apenas em análise retrospectiva sobre a série inteira.
    Nunca em teste temporal, reprodução datada ou qualquer coisa que alimente a H1.
    A coluna `titulo_retroalimentado` existe nos dois modos (toda `False` quando
    desligado), para que o consumidor da Silver não precise de um `if`.

    `nota`/`n_avaliacoes`/`preco` saem `NaN` quando a linha de origem também não tinha
    o campo: comportamento esperado (ver `test_amazon_silver_tipos_numericos`).
    """
    out = linhas_legitimas_amazon(df)
    out["categoria_parte_a"] = out["categoria_pagina"].map(_MAPA_VITRINE_CATEGORIA)

    rank_extraido = out["rank"].str.extract(_PADRAO_RANK)[0]
    if rank_extraido.isna().any():
        # Um `.astype(int)` direto derrubaria a Silver inteira com "Cannot convert
        # non-finite values to integer", sem contexto. A falha deve ser explícita e
        # legível, com amostra das linhas fora do padrão.
        ruins = out.loc[rank_extraido.isna(), ["categoria_pagina", "rank"]].head(5)
        raise ValueError(
            f"{int(rank_extraido.isna().sum())} linha(s) da Amazon com `rank` fora do "
            f"padrão '#N' — o formato da fonte pode ter mudado. Amostra:\n{ruins.to_string()}"
        )
    out["rank"] = rank_extraido.astype(int)

    aval = out["avaliacao"].str.extract(_PADRAO_AVALIACAO)
    out["nota"] = aval[0].str.replace(",", ".", regex=False).astype(float)
    out["n_avaliacoes"] = pd.to_numeric(aval[1].str.replace(".", "", regex=False), errors="coerce").astype("Int64")

    out["preco"] = _preco_para_float(out["preco"])

    # §3.2 item 8: backfill do `titulo` (ver a docstring acima).
    # Campo novo, com nome próprio: `titulo_retroalimentado` marca a linha recuperada,
    # para que título inferido não se confunda com título como servido pela fonte.
    # Item que nunca teve título em rodada nenhuma continua `NaN`: o backfill não inventa.
    out["titulo_retroalimentado"] = False
    if backfill_titulo:
        conhecidos = (
            out.loc[out["titulo"].notna()]
            .sort_values("coletado_em")
            .groupby("item_id")["titulo"]
            .first()
        )
        faltando = out["titulo"].isna()
        recuperado = out["item_id"].map(conhecidos)
        out["titulo_retroalimentado"] = faltando & recuperado.notna()
        out.loc[faltando, "titulo"] = recuperado[faltando]

    # §2.5: antes do dedup (ver item 6 da docstring acima).
    n_vitrine = out.groupby(["categoria_pagina", "coletado_em"])["rank"].transform("count")
    denom = (n_vitrine - 1).clip(lower=1)
    percentil = 1 - (out["rank"] - 1) / denom
    out["rank_percentil"] = percentil.where(n_vitrine > 1, 1.0)

    grupo = ["item_id", "categoria_parte_a", "coletado_em"]
    out["n_vitrines_publicando"] = out.groupby(grupo)["item_id"].transform("size")
    out = out.sort_values("rank", ascending=False).drop_duplicates(subset=grupo, keep="first")

    return out.sort_values(["coletado_em", "categoria_parte_a", "rank"]).reset_index(drop=True)


PREPARADORES = {
    "tcc_bronze_google_suggest": preparar_google_suggest,
    "tcc_bronze_youtube": preparar_youtube,
    "tcc_bronze_shopee": preparar_shopee,
    "tcc_bronze_ml": preparar_ml,
    "tcc_bronze_amazon": preparar_amazon,
}


def tabelas_da_silver(
    com_mercado_livre: bool = False, com_google_suggest: bool = False
) -> list[str]:
    """Quais tabelas Bronze viram Silver.

    Em 20/10 o Mercado Livre saiu da análise, da Silver em diante; o que foi coletado
    no Bronze fica como exemplo. O `preparar_ml` continua aqui, intacto: é ele que
    reproduz as medições datadas que usaram o ML até 06/10 (os pares do achado ⑤, a
    reanálise de 17/09), e só roda quando pedido com `com_mercado_livre=True`.

    Em 02/11 o Google Suggest também saiu: ele não carrega volume e nenhum resultado do
    trabalho o usava. O `preparar_google_suggest` fica, para quem pedir
    `com_google_suggest=True`.
    """
    fora = set()
    if not com_mercado_livre:
        fora.add("tcc_bronze_ml")
    if not com_google_suggest:
        fora.add("tcc_bronze_google_suggest")
    return [t for t in PREPARADORES if t not in fora]


def preparar_bronze(
    raw_dir: Path | None = None, com_mercado_livre: bool = False,
    com_google_suggest: bool = False, **kwargs
) -> dict[str, pd.DataFrame]:
    """Carrega cada tabela Bronze (via `carregar_bronze`) e aplica o preparador
    correspondente. Devolve um dict {nome_da_tabela: DataFrame preparado}.

    `**kwargs` é repassado ao `carregar_tabela`: é por onde se alcança a saída
    declarada dos guardas do loader (`idade_maxima_dias=None` para dado histórico de
    propósito, `conferir_integridade=False` para janela parcial intencional). Sem esse
    repasse, a saída existiria na documentação e não no caminho que a Silver usa.

    `com_mercado_livre=True` inclui o ML, só para as medições datadas (até 06/10), e
    `com_google_suggest=True` inclui o Suggest (até 02/11); ver `tabelas_da_silver`.
    """
    if raw_dir is not None:
        kwargs["raw_dir"] = raw_dir
    return {
        tabela: PREPARADORES[tabela](carregar_tabela(tabela, **kwargs))
        for tabela in tabelas_da_silver(com_mercado_livre, com_google_suggest)
    }


def _main() -> None:
    PROCESSADO_DIR.mkdir(parents=True, exist_ok=True)
    preparados = preparar_bronze()
    for tabela, df in preparados.items():
        nome_silver = tabela.replace("tcc_bronze_", "tcc_silver_")
        destino = PROCESSADO_DIR / f"{nome_silver}.csv"
        df.to_csv(destino, index=False, encoding="utf-8")
        print(f"{tabela}: {len(df)} linhas -> {destino}")


if __name__ == "__main__":
    _main()
