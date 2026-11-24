# -*- coding: utf-8 -*-
"""A variável líder da H1: carregar o Trends manual e caracterizá-lo.

Por que existe. A H1 diz que o momentum de busca antecipa a venda, e até 01/09 esse
momentum não tinha sido operacionalizado: o Suggest não carrega volume (quatro sondas
independentes) e a fonte de magnitude, o Google Trends, tinha saído do plano em 25/07.
A coleta manual de 02 a 07/09 (`02_Dados/trends/PLANO_TRENDS.md`) devolveu o
instrumento: 129 termos com resolução útil, em resolução diária.

Este módulo faz dois passos, e nenhum deles é o teste da H1:

1. Carregar as metades num alvo único por (termo, dia): `carregar_trends`.
2. Caracterizar a série, para que a escolha da operacionalização seja medida e não
   copiada de outro instrumento: `caracterizar`.

O que o módulo deliberadamente não faz: padronizar. O `PLANO_TRENDS.md` prevê padronizar
cada metade e concatenar, e isso foi escrito para correlação. Padronizar aqui amarraria
as três operacionalizações candidatas a uma delas (o z-score é a candidata C); por isso
o carregador guarda o valor bruto e o bloco de origem, e a padronização fica a cargo de
quem a usar. A escala do Trends é por lote, logo o bloco é a unidade dentro da qual o
valor é comparável, e é ele que impede qualquer janela de atravessar a emenda
`15/08 → 17/08`.

Também não cria régua própria: dono do termo, piso, dia anômalo e zero suspeito vêm do
`conferir_trends.py`, que é o auditor da coleta. Régua nova aqui seria um segundo
critério para o mesmo fato.

Uso:

    06_enxame_api/.venv/Scripts/python 03_Analise/momentum_busca.py
    06_enxame_api/.venv/Scripts/python 03_Analise/momentum_busca.py --com-alvo
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conferir_trends import (  # noqa: E402
    Lote,
    donos_da_janela,
    donos_da_janela_a,
    janela_do_lote,
    par_na_janela,
    piso_para,
)

RAIZ = Path(__file__).resolve().parent.parent
PASTA_TRENDS = RAIZ / "02_Dados" / "trends"

# A emenda. O dia `16/08/2026` está quebrado na fonte e mudou de comportamento em 03/09,
# por isso a coleta virou duas janelas. Nenhuma janela móvel pode atravessar esta data:
# os dias não são contíguos e a escala de cada metade é própria. O bloco é o que garante
# isso, e não uma checagem de data espalhada pelo código.
DIA_DA_EMENDA = "2026-08-16"

# O ruído branco puro tem desvio(delta)/desvio(nível) = sqrt(2) e desvio(MM7)/desvio(x)
# = 1/sqrt(7). São as duas réguas usadas para descartar o delta diário do buzz em 01/09,
# reproduzidas aqui de propósito para que os dois instrumentos sejam comparáveis.
RUIDO_RAZAO_DELTA = 2 ** 0.5        # 1,414
RUIDO_RAZAO_MM7 = 7 ** -0.5         # 0,378


# ---------------------------------------------------------------------------
# Passo 1: carregar
# ---------------------------------------------------------------------------


def _serie_do_termo(lote: Lote, termo: str) -> list[tuple[str, float | None, bool]]:
    """(dia, valor, censurado) do termo num lote, já com os nulos aplicados.

    Há dois tipos de nulo, e a distinção importa (`PLANO_TRENDS.md`):
    * dia anômalo: o lote inteiro falhou naquele dia (linha zerada, ou salto de 10×);
    * zero suspeito: a fonte falhou para aquele termo num dia em que os vizinhos
      seguem normais. A regra de anular é por (termo, dia), nunca por data.

    Zero falso vira queda falsa e contamina a correlação (a mesma armadilha do campo
    `sales`); por isso o zero suspeito é nulo e não zero.
    """
    anomalos = set(lote.dias_anomalos())
    suspeitos = {
        dia for dia, termos in lote.zeros_suspeitos().items()
        if any(t.startswith(termo) for t in termos)
    }
    saida: list[tuple[str, float | None, bool]] = []
    for dia, cru in zip(lote.dias, lote.valores[termo]):
        if dia in anomalos or dia in suspeitos:
            saida.append((dia, None, False))
            continue
        saida.append((dia, Lote.num(cru), cru == "<1"))
    return saida


def carregar_trends(pasta: Path = PASTA_TRENDS) -> pd.DataFrame:
    """O Trends manual num quadro longo: termo × dia, com o bloco de origem.

    Colunas: `termo`, `dia`, `valor`, `bloco`, `metade`, `censurado`. `metade` é `a`
    (09/07 a 15/08), `b` (17/08 a 06/09) ou `c` (07/09 a 19/10, a do experimento 2).

    `bloco` é a unidade de escala: o arquivo de onde a série daquele termo saiu.
    Termo com as duas metades tem dois blocos; o valor não é comparável entre eles,
    e nenhuma janela móvel deve cruzá-los.
    """
    lotes = [Lote(p) for p in sorted(pasta.glob("trends_lote*.csv")) if Lote(p).dias]
    dono_a = donos_da_janela_a(lotes)
    por_nome = {l.nome: l for l in lotes}

    linhas: list[dict] = []
    vistos: set[tuple[str, str]] = set()

    def anexar(lote: Lote, termo: str, metade: str) -> None:
        if (termo, lote.nome) in vistos:
            return
        vistos.add((termo, lote.nome))
        for dia, valor, censurado in _serie_do_termo(lote, termo):
            linhas.append({
                "termo": termo, "dia": dia, "valor": valor,
                "bloco": lote.nome, "metade": metade, "censurado": censurado,
            })

    # (1) quem tem dono na janela `a`: a série sai do arquivo-dono, não de qualquer aparição
    for termo, (arquivo, _d, _piso) in dono_a.items():
        anexar(por_nome[arquivo], termo, "a")
        par_b = por_nome.get(par_na_janela(arquivo, "b"))
        if par_b is not None and termo in par_b.termos:
            piso_b = piso_para(len(par_b.dias) - len(par_b.dias_anomalos()))
            if par_b.distintos(termo, ignorar=set(par_b.dias_anomalos())) > piso_b:
                anexar(par_b, termo, "b")

    # (2) os que só resolvem na metade `b`: 21 dias soltos, sem `a` para emendar
    for lote in lotes:
        if janela_do_lote(lote.nome) != "b":
            continue
        piso = piso_para(len(lote.dias) - len(lote.dias_anomalos()))
        anomalos = set(lote.dias_anomalos())
        for termo in lote.termos:
            if termo in dono_a or termo in {l["termo"] for l in linhas}:
                continue
            if lote.distintos(termo, ignorar=anomalos) > piso:
                anexar(lote, termo, "b")

    # (3) a janela `c` (07/09 → 19/10), a única que o experimento 2 lê. A série sai do
    # arquivo `c` de maior folga, e não do par do dono antigo: ela nunca é emendada a nada
    # (o experimento 2 só usa busca posterior a 06/09), então o que importa nela é a
    # resolução. Bloco próprio: nenhuma janela móvel cruza de 06/09 para 07/09, mesmo com
    # os dias contíguos, porque a escala de cada arquivo é própria.
    for termo, (arquivo, _d, _piso) in donos_da_janela(lotes, "c").items():
        anexar(por_nome[arquivo], termo, "c")

    df = pd.DataFrame(linhas)
    df["dia"] = pd.to_datetime(df["dia"]).dt.date
    return df.sort_values(["termo", "dia"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Passo 2: caracterizar (medir, não decidir)
# ---------------------------------------------------------------------------


def _sem_dia_da_semana(serie: pd.Series) -> pd.Series:
    """A série menos a média do próprio dia-da-semana (dentro do bloco).

    Existe porque as réguas do buzz medem duas coisas ao mesmo tempo neste dado.
    Um ciclo de período 7 produz autocorrelação lag-1 do delta negativa por construção,
    e uma MM7 sobre ele remove o ciclo inteiro. Logo, num dado com calendário forte,
    "autocorr −0,35" e "razão MM7 abaixo do ruído" são o que se espera de uma série com
    estrutura, não de ruído. Aplicar a régua sem condicionar responde à pergunta do buzz,
    não a esta.
    """
    dias = pd.to_datetime(pd.Series(list(serie.index)))
    dow = pd.Series(dias.dt.dayofweek.values, index=serie.index)
    return serie - serie.groupby(dow).transform("mean")


def perfil_do_ruido(
    df: pd.DataFrame, minimo_dias: int = 20, deszonalizar: bool = False
) -> pd.DataFrame:
    """Por termo: o delta diário é sinal ou é ruído de estimador?

    As três réguas são as que descartaram o delta diário do buzz em 01/09, e estão aqui
    para que a resposta seja comparável, não intuída:

    * `autocorr_delta`: autocorrelação lag-1 de Δx. Próxima de −0,5 é reversão típica
      de estimador; o buzz deu −0,40, com 60% dos termos abaixo de −0,3.
    * `razao_delta`: desvio(Δx)/desvio(x). O ruído branco puro dá 1,414; o buzz deu
      1,16, ou seja, quase indistinguível de ruído.
    * `razao_mm7`: desvio(MM7)/desvio(x). O ruído puro dá 0,378: acima disso sobra
      sinal lento. No buzz foi 0,465, e 27 de 63 termos passaram de 0,60.

    `deszonalizar=True` remove o dia da semana antes de medir (ver `_sem_dia_da_semana`).
    As duas leituras são reportadas lado a lado, porque a diferença entre elas é a
    resposta: se a autocorrelação sobe para perto de zero ao tirar o calendário, o que
    parecia ruído era o fim de semana.

    Tudo é calculado dentro do bloco: janela que cruza a emenda mistura escalas.
    """
    saida: list[dict] = []
    for (termo, bloco), g in df.groupby(["termo", "bloco"], sort=False):
        serie = g.set_index("dia")["valor"].astype(float)
        if serie.notna().sum() < minimo_dias:
            continue
        if deszonalizar:
            serie = _sem_dia_da_semana(serie)
        delta = serie.diff()
        mm7 = serie.rolling(7, min_periods=7).mean()   # trailing: nunca center=True
        dp = serie.std()
        saida.append({
            "termo": termo,
            "bloco": bloco,
            "metade": g["metade"].iloc[0],
            "dias": int(serie.notna().sum()),
            "autocorr_delta": delta.autocorr(lag=1),
            "razao_delta": (delta.std() / dp) if dp else float("nan"),
            "razao_mm7": (mm7.std() / dp) if dp else float("nan"),
        })
    return pd.DataFrame(saida)


def ciclo_semanal(df: pd.DataFrame, minimo_dias: int = 20) -> pd.DataFrame:
    """Por termo: quanto da variância o dia da semana explica (eta²).

    Isto vem antes de qualquer correlação porque todos os termos sobem e descem juntos
    no fim de semana. Correlação busca × venda sem tratar o calendário mede calendário,
    não demanda; o efeito é o mesmo nas duas séries, então não se cancela: infla a
    correlação. Se o eta² for alto, a MM7 deixa de ser escolha estética e passa a ser
    controle, pois remove o ciclo semanal por construção.
    """
    saida: list[dict] = []
    for (termo, bloco), g in df.groupby(["termo", "bloco"], sort=False):
        g = g.dropna(subset=["valor"])
        if len(g) < minimo_dias:
            continue
        dow = pd.to_datetime(pd.Series(list(g["dia"]))).dt.dayofweek
        valores = g["valor"].astype(float).reset_index(drop=True)
        total = ((valores - valores.mean()) ** 2).sum()
        entre = sum(
            len(sub) * (sub.mean() - valores.mean()) ** 2
            for _, sub in valores.groupby(dow)
        )
        saida.append({
            "termo": termo, "bloco": bloco,
            "eta2_dia_da_semana": (entre / total) if total else float("nan"),
        })
    return pd.DataFrame(saida)


def momentum(df: pd.DataFrame, qual: str) -> pd.DataFrame:
    """As três operacionalizações do `protocolo_lead_lag_h1.py` §2, em forma executável.

        A_media_movel .... MM7_t / MM7_{t-7} - 1
        B_variacao_pct ... x_t / x_{t-7} - 1
        C_desvio_base .... (MM7_t - média(MM7_{t-14..t-1})) / desvio(MM7_{t-14..t-1})

    Todas usam passo 7, escolha que saiu de medição: o dia da semana explica 36% da
    variância desta série, então qualquer passo 1 mediria calendário. Nenhuma estima
    fator sazonal: o passo 7 o neutraliza sem custo (MM7 anula o ciclo; `t` contra
    `t-7` é o mesmo dia da semana).

    Tudo dentro do bloco (R2) e tudo trailing (R1): o `shift(1)` nas janelas de C
    existe para que a base não inclua o próprio dia. `center=True` é proibido.
    """
    from protocolo_lead_lag_h1 import JANELA_BASE_C, JANELA_MM, PASSO_SAZONAL

    saida = []
    for (termo, bloco), g in df.groupby(["termo", "bloco"], sort=False):
        g = g.sort_values("dia")
        x = g.set_index("dia")["valor"].astype(float)
        mm = x.rolling(JANELA_MM, min_periods=JANELA_MM).mean()   # trailing
        if qual == "A_media_movel":
            v = mm / mm.shift(PASSO_SAZONAL) - 1
        elif qual == "B_variacao_pct":
            v = x / x.shift(PASSO_SAZONAL) - 1
        elif qual == "C_desvio_base":
            base = mm.shift(1)          # a base não inclui o dia corrente
            media = base.rolling(JANELA_BASE_C, min_periods=JANELA_BASE_C).mean()
            desvio = base.rolling(JANELA_BASE_C, min_periods=JANELA_BASE_C).std()
            v = (mm - media) / desvio
        else:
            raise ValueError(f"operacionalizacao desconhecida: {qual}")
        saida.append(pd.DataFrame({
            "termo": termo, "bloco": bloco, "metade": g["metade"].iloc[0],
            "dia": v.index, "momentum": v.values,
        }))
    out = pd.concat(saida, ignore_index=True)
    return out.replace([float("inf"), float("-inf")], pd.NA)


def custo_das_operacionalizacoes(df: pd.DataFrame) -> pd.DataFrame:
    """Quantas observações cada operacionalização sobra, por metade.

    Mede o custo de aquecimento de cada operacionalização em vez de estimá-lo, porque
    estimativa dentro de um pré-registro seria afirmação sem verificação.
    """
    from protocolo_lead_lag_h1 import OPERACIONALIZACOES

    linhas = []
    for qual in OPERACIONALIZACOES:
        m = momentum(df, qual).dropna(subset=["momentum"])
        for metade, g in m.groupby("metade"):
            por_termo = g.groupby("termo").size()
            linhas.append({
                "operacionalizacao": qual,
                "metade": metade,
                "termos": g["termo"].nunique(),
                "obs": len(g),
                "mediana_pts_por_termo": float(por_termo.median()),
            })
    return pd.DataFrame(linhas)


def sobreposicao_com_alvo(df: pd.DataFrame, alvo: pd.DataFrame) -> dict:
    """Quantos termos-dia têm busca e venda: o número que dimensiona o teste.

    Conta por termo o nº de dias com os dois lados presentes; é ele, e não o total de
    termos do Trends, que diz de quantas séries o lead-lag dispõe.
    """
    busca = df.dropna(subset=["valor"])[["termo", "dia"]].drop_duplicates()
    venda = alvo[["termo", "dia"]].drop_duplicates()
    venda = venda.assign(dia=pd.to_datetime(venda["dia"]).dt.date)
    juntos = busca.merge(venda, on=["termo", "dia"], how="inner")
    por_termo = juntos.groupby("termo").size().sort_values(ascending=False)
    return {
        "termos_busca": busca["termo"].nunique(),
        "termos_alvo": venda["termo"].nunique(),
        "termos_com_os_dois": len(por_termo),
        "com_30_dias": int((por_termo >= 30).sum()),
        "com_42_dias": int((por_termo >= 42).sum()),
        "mediana_dias": float(por_termo.median()) if len(por_termo) else 0.0,
        "por_termo": por_termo,
    }


def _resumo(serie: pd.Series) -> str:
    return (
        f"mediana {serie.median():+.3f} · "
        f"p10 {serie.quantile(0.10):+.3f} · p90 {serie.quantile(0.90):+.3f}"
    )


def _main() -> None:
    com_alvo = "--com-alvo" in sys.argv

    df = carregar_trends()
    print("=== PASSO 1 — o Trends num alvo unico ===")
    print(f"  linhas (termo x dia) ........ {len(df):,}".replace(",", "."))
    print(f"  termos ...................... {df['termo'].nunique()}")
    print(f"  blocos (arquivos-dono) ...... {df['bloco'].nunique()}")
    print(f"  dias .............. {df['dia'].min()} -> {df['dia'].max()}")
    nulos = df["valor"].isna().sum()
    print(f"  nulos (dia anomalo/zero susp) {nulos} ({nulos / len(df):.1%})")
    print(f"  censurados '<1' ............. {int(df['censurado'].sum())}")
    por_metade = df.groupby("termo")["metade"].nunique()
    print(f"  termos com as DUAS metades .. {int((por_metade == 2).sum())}")
    print(f"  termos com UMA metade ....... {int((por_metade == 1).sum())}")

    print("\n=== PASSO 2b — o calendario confunde? (vem ANTES, e por isso) ===")
    semana = ciclo_semanal(df)
    print(f"  eta2 do dia-da-semana ....... {_resumo(semana['eta2_dia_da_semana'])}")
    forte = (semana["eta2_dia_da_semana"] > 0.20).sum()
    print(f"  series com eta2 > 0,20 ...... {forte} de {len(semana)}")

    print("\n=== PASSO 2 — a MM e necessaria, ou eu copiaria a solucao do buzz? ===")
    for rotulo, desz in (("CRU", False), ("SEM dia-da-semana", True)):
        ruido = perfil_do_ruido(df, deszonalizar=desz)
        so_a = ruido[ruido["metade"] == "a"]
        print(f"\n  --- {rotulo} --- ({len(ruido)} series, das quais {len(so_a)} da metade 'a')")
        print(f"  autocorr lag-1 do delta ..... {_resumo(ruido['autocorr_delta'])}")
        print(f"        so a metade 'a' ....... {_resumo(so_a['autocorr_delta'])}")
        print(f"        (buzz em 01/09: -0,40 — reversao tipica de estimador)")
        print(f"  desvio(delta)/desvio(nivel) . {_resumo(ruido['razao_delta'])}")
        print(f"        (ruido branco puro: {RUIDO_RAZAO_DELTA:.3f} · buzz: 1,16)")
        print(f"  desvio(MM7)/desvio(bruto) ... {_resumo(ruido['razao_mm7'])}")
        print(f"        (ruido branco puro: {RUIDO_RAZAO_MM7:.3f} · buzz: 0,465)")
        acima = (ruido["razao_mm7"] > 0.60).sum()
        print(f"  series com razao_mm7 > 0,60 . {acima} de {len(ruido)}")

    if not com_alvo:
        print("\n(rode com --com-alvo para cruzar com o alvo da H1; le o Bronze)")
        return

    from alvo_h1 import construir_alvo  # import tardio: le o Bronze, e e caro

    print("\n=== PASSO 2c — de quantas series o lead-lag dispoe? ===")
    alvo = construir_alvo()["alvo"]
    s = sobreposicao_com_alvo(df, alvo)
    print(f"  termos com busca ............ {s['termos_busca']}")
    print(f"  termos com venda ............ {s['termos_alvo']}")
    print(f"  termos com OS DOIS .......... {s['termos_com_os_dois']}")
    print(f"    ... com 30+ dias .......... {s['com_30_dias']}")
    print(f"    ... com 42+ dias .......... {s['com_42_dias']}")
    print(f"    mediana de dias ........... {s['mediana_dias']:.0f}")


if __name__ == "__main__":
    _main()
