# -*- coding: utf-8 -*-
"""Experimento 1 do lead-lag da H1: a execução do `protocolo_lead_lag_h1.py`.

Este arquivo não decide nada. Toda régua que ele aplica vem do protocolo, commitado em
`377a653` antes de qualquer resultado existir, mais a emenda §8 de 08/09, commitada
antes da primeira execução. Se este script e o protocolo divergirem, vale o protocolo,
e a divergência é defeito deste script.

O que ele faz, na ordem do protocolo:

1. carrega o Trends (`momentum_busca.carregar_trends`) e o alvo (`alvo_h1`);
2. para cada operacionalização (A primária, B e C robustez) e cada lag `k = 0..14`,
   correlaciona momentum em `t-k` contra alvo em `t`, por termo, e agrega pela
   mediana e pela fração de termos positivos;
3. reporta os alvos lado a lado: quatro desde 15/09 (unificado, Shopee, Amazon e ML;
   emendas E8.2 e E9.1);
4. roda os dois placebos: P1 lags invertidos e P2 alvo embaralhado entre termos,
   1.000 permutações, que é o que resolve a multiplicidade dos 15 lags sem Bonferroni.

O resultado é exploratório por definição do projeto (01/09 e 08/09), e nenhum p-valor
daqui se reporta como confirmação. O experimento 1 gera a hipótese específica (qual
operacionalização, qual lag, qual sinal); o experimento 2 a testa em dado novo, com
essa escolha já fixada. É essa sequência, declarada antes, que separa isto de garimpar
especificação.

O artefato de 08/09 não pode ser sobrescrito. Os destinos padrão são caminhos fixos
(`02_Dados/resultado_lead_lag_h1.json` e `comparacao_lead_lag_h1.csv`), e rodar de novo
destruiria a prova do experimento 1, que está commitada. Por isso o artefato declara
`fontes_do_alvo`, e o gravador é fail-closed: recusa-se a escrever por cima de um
artefato de composição diferente (ou sem o campo, que é a assinatura dos de 08/09) e
indica qual `--rotulo` usar.

Uso:

    06_enxame_api/.venv/Scripts/python 03_Analise/experimento_lead_lag_h1.py
    06_enxame_api/.venv/Scripts/python 03_Analise/experimento_lead_lag_h1.py --rapido
    # a reanálise de 17/09, com o ML no alvo (3 fontes), em artefato próprio:
    ... experimento_lead_lag_h1.py --rotulo reanalise_3fontes
    ... experimento_lead_lag_h1.py --comparar --rotulo reanalise_3fontes
    # o controle positivo: reproduzir o alvo de duas fontes pelo caminho atual
    ... experimento_lead_lag_h1.py --rapido --duas-fontes
    # o experimento 1 exato, desde 30/09 (a regra de Artes mudou o classificador, §8f):
    ... experimento_lead_lag_h1.py --duas-fontes --sem-regras-artes --rotulo <nome>
    # o experimento 2 (§8d e §8e do protocolo), um único disparo, após o download de 06/10+:
    ... experimento_lead_lag_h1.py --experimento-2

O experimento 2 foi incluído neste arquivo em 30/09, antes do dado. Ele roda só sobre
busca posterior a `06/09` (§1), com a primária B no `alvo_unificado`, o máximo na faixa
`8..12` contra o nulo do máximo na mesma faixa (R8d.3), as três fontes ao lado (R8d.2)
e a robustez com a composição descontada nas quatro séries (§8e), lida pela R8e.3. Ele se
recusa a rodar se a condição da §1 não se cumprir, com `--rapido` (rodar rápido também é
olhar o dado) ou se o artefato já existir: um experimento confirmatório tem uma execução só.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from momentum_busca import carregar_trends, momentum  # noqa: E402
from protocolo_lead_lag_h1 import (  # noqa: E402
    ALVO_PRIMARIO,
    ALVOS,
    ALVOS_ROBUSTEZ_COMPOSICAO,
    DESCONTO_COMPOSICAO,
    DIAS_NOVOS_PARA_EXPERIMENTO_2,
    FAIXA_LAG_EXPERIMENTO_2,
    FONTES_DO_ALVO_EXPERIMENTO_2,
    LAG_MINIMO_PRIMARIA,
    LAGS,
    LAGS_EXPERIMENTO_2,
    LAGS_PLACEBO_INVERTIDO,
    MINIMO_PARES_POR_TERMO,
    N_PERMUTACOES,
    OPERACIONALIZACOES,
    PERCENTIL_CORTE,
    PRIMARIA,
    PRIMARIA_EXPERIMENTO_2,
    TERMOS_MINIMOS_PARA_EXPERIMENTO_2,
    ULTIMO_DIA_DE_BUSCA,
)

RAIZ = Path(__file__).resolve().parent.parent


def fontes_do_alvo(alvo: pd.DataFrame) -> list[str]:
    """Quais fontes de venda o painel carrega, lido das colunas, nunca do rótulo.

    Seleção por rótulo quebra quando o universo cresce: o rótulo não fica errado, mas
    passa a descrever corretamente uma população menor que a real.
    """
    return [c.replace("alvo_", "") for c in ("alvo_shopee", "alvo_amazon", "alvo_ml") if c in alvo.columns]


def _destino(nome: str, rotulo: str | None) -> Path:
    if rotulo:
        raiz, sufixo = nome.rsplit(".", 1)
        nome = f"{raiz}_{rotulo}.{sufixo}"
    return RAIZ / "02_Dados" / nome


def _gravar_fail_closed(destino: Path, conteudo: str, fontes: list[str]) -> None:
    """Grava só se o destino não existir ou já for da mesma composição de fontes.

    Sem isto, rodar a reanálise de 3 fontes apagaria o experimento 1, que está commitado.
    Artefato antigo não tem `fontes_do_alvo`; a ausência do campo identifica esses artefatos e
    também bloqueia a gravação.
    """
    if destino.exists():
        try:
            antigo = json.loads(destino.read_text(encoding="utf-8")).get("fontes_do_alvo")
        except (json.JSONDecodeError, UnicodeDecodeError):
            antigo = None
        if antigo != fontes:
            raise SystemExit(
                f"\nRECUSADO: {destino.name} ja existe com fontes_do_alvo={antigo}, e esta\n"
                f"   rodada tem {fontes}. Sobrescrever apagaria um artefato de OUTRA composicao.\n"
                f"   → use --rotulo <nome> (ex.: --rotulo reanalise_3fontes).\n"
            )
    destino.write_text(conteudo, encoding="utf-8")


# ---------------------------------------------------------------------------
# A correlação implementada diretamente: o venv de análise não tem scipy
# ---------------------------------------------------------------------------


def _postos(v: np.ndarray) -> np.ndarray:
    """Postos com empate resolvido pela média, que é o que Spearman exige.

    Implementado diretamente porque o venv de análise não tem scipy; dá a mesma saída
    de `rankdata(..., method="average")`.
    """
    n = len(v)
    ordem = np.argsort(v, kind="mergesort")
    postos = np.empty(n, dtype=float)
    postos[ordem] = np.arange(1, n + 1, dtype=float)
    ordenado = v[ordem]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordenado[j + 1] == ordenado[i]:
            j += 1
        if j > i:
            postos[ordem[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return postos


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman = Pearson sobre os postos. NaN se não houver variação nos dois lados."""
    if len(x) < 3:
        return float("nan")
    rx, ry = _postos(x), _postos(y)
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    den = np.sqrt((rx * rx).sum() * (ry * ry).sum())
    return float((rx * ry).sum() / den) if den > 0 else float("nan")


# ---------------------------------------------------------------------------
# O painel denso: termos × dias, o que torna 1.000 permutações viáveis
# ---------------------------------------------------------------------------


def montar_painel(mom: pd.DataFrame, alvo: pd.DataFrame, coluna_alvo: str):
    """(M, Y, termos, dias): duas matrizes termo × dia, alinhadas pelo calendário.

    `M[i, d]` é o momentum do termo `i` no dia `d`; `Y[i, d]` é o alvo. O lag entra
    depois, deslocando M no eixo do dia, o que equivale a parear `momentum(t-k)` com
    `alvo(t)` e mantém o pareamento por data, não por posição na série do termo.

    A emenda `15/08 → 17/08` não precisa de tratamento aqui: ela já foi respeitada no
    cálculo do momentum, dentro do bloco (R2). O pareamento com o alvo pode atravessá-la,
    porque o alvo é contínuo e a proibição é sobre a janela, não sobre o par.
    """
    m = mom.dropna(subset=["momentum"]).copy()
    a = alvo[["termo", "dia", coluna_alvo]].dropna(subset=[coluna_alvo]).copy()
    m["dia"] = pd.to_datetime(m["dia"])
    a["dia"] = pd.to_datetime(a["dia"])

    termos = sorted(set(m["termo"]) & set(a["termo"]))
    if not termos:
        vazio = np.zeros((0, 0))
        return vazio, vazio, [], []
    dias = pd.date_range(
        min(m["dia"].min(), a["dia"].min()), max(m["dia"].max(), a["dia"].max()), freq="D"
    )
    i_termo = {t: i for i, t in enumerate(termos)}
    i_dia = {d: j for j, d in enumerate(dias)}

    M = np.full((len(termos), len(dias)), np.nan)
    Y = np.full((len(termos), len(dias)), np.nan)
    for termo, dia, v in zip(m["termo"], m["dia"], m["momentum"]):
        if termo in i_termo:
            M[i_termo[termo], i_dia[dia]] = v
    for termo, dia, v in zip(a["termo"], a["dia"], a[coluna_alvo]):
        if termo in i_termo:
            Y[i_termo[termo], i_dia[dia]] = v
    return M, Y, termos, list(dias)


def _desloca(M: np.ndarray, k: int) -> np.ndarray:
    """M[i, d] passa a conter o momentum de `d - k`: o líder alinhado ao dia do alvo."""
    out = np.full_like(M, np.nan)
    if k == 0:
        out[:] = M
    elif k > 0:
        out[:, k:] = M[:, :-k]
    else:
        out[:, :k] = M[:, -k:]
    return out


def correlacoes_por_termo(
    M: np.ndarray, Y: np.ndarray, k: int, minimo: int = MINIMO_PARES_POR_TERMO
) -> np.ndarray:
    """ρ de Spearman por termo, no lag `k`. NaN em termo com menos de `minimo` pares.

    O piso de pares é a emenda E8.1 e vale aqui e no placebo: aplicá-lo só no
    observado compararia um observado filtrado contra um nulo mais frouxo.
    """
    Mk = _desloca(M, k)
    valido = ~np.isnan(Mk) & ~np.isnan(Y)
    fora = np.full(M.shape[0], np.nan)
    for i in range(M.shape[0]):
        v = valido[i]
        if v.sum() < minimo:
            continue
        fora[i] = spearman(Mk[i, v], Y[i, v])
    return fora


def curva_de_lags(M, Y, lags=LAGS, minimo=MINIMO_PARES_POR_TERMO) -> pd.DataFrame:
    """Para cada lag: mediana de ρ, fração de termos positivos e nº de termos."""
    linhas = []
    for k in lags:
        rho = correlacoes_por_termo(M, Y, k, minimo)
        bons = rho[~np.isnan(rho)]
        linhas.append({
            "lag": k,
            "termos": len(bons),
            "mediana_rho": float(np.median(bons)) if len(bons) else float("nan"),
            "fracao_positiva": float((bons > 0).mean()) if len(bons) else float("nan"),
        })
    return pd.DataFrame(linhas)


def estatistica_primaria(curva: pd.DataFrame, lag_minimo=LAG_MINIMO_PRIMARIA) -> dict:
    """`max_k mediana(ρ_k)` para `k >= 1`: a estatística que o protocolo §4 declara."""
    c = curva[curva["lag"] >= lag_minimo].dropna(subset=["mediana_rho"])
    if c.empty:
        return {"valor": float("nan"), "lag": None}
    linha = c.loc[c["mediana_rho"].idxmax()]
    return {"valor": float(linha["mediana_rho"]), "lag": int(linha["lag"])}


# ---------------------------------------------------------------------------
# P2: o placebo que resolve a multiplicidade
# ---------------------------------------------------------------------------


def permutacao_p2(M, Y, n=N_PERMUTACOES, semente=20260908, minimo=MINIMO_PARES_POR_TERMO,
                  lags=None):
    """Distribuição do máximo sob o nulo, embaralhando o pareamento termo↔termo.

    `lags=None` é o alcance do experimento 1 (`k = 1..14`) e reproduz o artefato de 08/09,
    com a mesma semente e os mesmos sorteios. O experimento 2 passa a faixa (`8..12`,
    R8d.3): o nulo tem de ser o máximo sobre o mesmo alcance do observado.

    Por que embaralhar resolve a multiplicidade: a estatística primária é um máximo
    sobre 15 lags, e comparar cada lag contra um p-valor nominal acharia significância por
    acaso. Aqui compara-se o máximo observado contra a distribuição do máximo sob o
    nulo, que já embute a busca pelos lags.

    Por que embaralhar preserva o que precisa ser preservado: cada série de alvo entra
    inteira, num termo errado. A autocorrelação de cada série sobrevive; o que se destrói
    é só o pareamento, que é exatamente a hipótese em teste.
    """
    rng = np.random.default_rng(semente)
    lags_primaria = [k for k in LAGS if k >= LAG_MINIMO_PRIMARIA] if lags is None else list(lags)
    maximos = np.empty(n)
    n_termos = M.shape[0]
    for p in range(n):
        sigma = rng.permutation(n_termos)
        while np.any(sigma == np.arange(n_termos)) and n_termos > 1 and p == 0:
            sigma = rng.permutation(n_termos)   # a 1a nunca é a identidade
        Yp = Y[sigma]
        medianas = []
        for k in lags_primaria:
            rho = correlacoes_por_termo(M, Yp, k, minimo)
            bons = rho[~np.isnan(rho)]
            medianas.append(np.median(bons) if len(bons) else np.nan)
        medianas = [x for x in medianas if not np.isnan(x)]
        maximos[p] = max(medianas) if medianas else np.nan
    return maximos[~np.isnan(maximos)]


# ---------------------------------------------------------------------------
# Experimento 2: a especificação da §8d e a robustez da §8e do protocolo
# ---------------------------------------------------------------------------
# Escrito e commitado antes de o dado novo existir (download em 06/10 ou depois).
# Nada daqui é chamado pelo experimento 1 nem pela reanálise de 17/09.

# §1: o experimento 2 testa em dado que ainda não existia: a busca posterior ao
# último dia da coleta que o experimento 1 viu. Momentum de antes disso não entra.
PRIMEIRO_DIA_DE_BUSCA_EXP2 = pd.Timestamp(ULTIMO_DIA_DE_BUSCA) + pd.to_timedelta(1, unit="D")
SEMENTE_EXP2 = 20260930   # fixada antes do dado, como a do experimento 1
ARTEFATO_EXP2 = "resultado_lead_lag_h1_experimento_2.json"


def condicao_experimento_2(trends: pd.DataFrame) -> dict:
    """A condição da §1, em forma executável: ≥ 30 dias de busca nova para ≥ 60 termos."""
    t = trends[pd.to_datetime(trends["dia"]) >= PRIMEIRO_DIA_DE_BUSCA_EXP2]
    t = t[t["valor"].notna()]
    dias = t.groupby("termo")["dia"].nunique()
    com_dias = int((dias >= DIAS_NOVOS_PARA_EXPERIMENTO_2).sum())
    return {
        "primeiro_dia_de_busca": str(PRIMEIRO_DIA_DE_BUSCA_EXP2.date()),
        "termos_com_dias_suficientes": com_dias,
        "dias_exigidos": DIAS_NOVOS_PARA_EXPERIMENTO_2,
        "termos_exigidos": TERMOS_MINIMOS_PARA_EXPERIMENTO_2,
        "cumprida": com_dias >= TERMOS_MINIMOS_PARA_EXPERIMENTO_2,
    }


def conferir_composicao_experimento_2(alvo: pd.DataFrame) -> list[str]:
    """R8h.3 (emenda de 20/10): o alvo do experimento 2 é Shopee + Amazon, e nada além.

    Lido das colunas (não do rótulo) e checado antes de medir: trocar a composição depois
    de ver o desfecho seria escolher o objeto pelo resultado. Fica fora do
    `rodar_experimento_2`, que é o motor e é exercitado com painéis sintéticos de qualquer
    composição.
    """
    fontes = fontes_do_alvo(alvo)
    if fontes != list(FONTES_DO_ALVO_EXPERIMENTO_2):
        raise ValueError(
            f"alvo do experimento 2 com fontes {fontes}; a §8h fixou "
            f"{list(FONTES_DO_ALVO_EXPERIMENTO_2)} em 20/10 — nada foi medido")
    return fontes


def estatistica_na_faixa(curva: pd.DataFrame, lags=LAGS_EXPERIMENTO_2) -> dict:
    """`max_k mediana(ρ_k)` com `k` na faixa `8..12`: a estatística primária da R8d.3."""
    c = curva[curva["lag"].isin(list(lags))].dropna(subset=["mediana_rho"])
    if c.empty:
        return {"valor": float("nan"), "lag": None}
    linha = c.loc[c["mediana_rho"].idxmax()]
    return {"valor": float(linha["mediana_rho"]), "lag": int(linha["lag"])}


def alvo_sem_composicao(alvo: pd.DataFrame) -> pd.DataFrame:
    """R8e.1: cada fonte descontada do seu nº de itens dentro do termo; o unificado sem
    composição é a média dos resíduos das fontes presentes no termo-dia.

    Centrar cada fonte dentro do termo remove também o canal da entrada e saída de fontes
    (a alternativa recusada, descontar o total, não o capta). O ajuste usa só as linhas
    recebidas: quem chama passa a janela do experimento 2, e é sobre ela que se estima.
    """
    from composicao_alvo_h1 import FONTES, descontar_composicao

    a = alvo.copy()
    residuos = []
    for f in FONTES:
        if f"alvo_{f}" in a.columns and f"n_itens_{f}" in a.columns:
            a[f"alvo_{f}_sem_composicao"] = descontar_composicao(a, f)
            residuos.append(f"alvo_{f}_sem_composicao")
    if residuos:
        a["alvo_unificado_sem_composicao"] = a[residuos].mean(axis=1)
    return a


def veredito_experimento_2(primaria_digna: bool, robustez_digna: bool) -> str:
    """R8e.3: a primária decide o veredito; a robustez decide o que ele pode afirmar."""
    if primaria_digna and robustez_digna:
        return "digno de replicacao e sobrevivente ao desconto da composicao"
    if primaria_digna:
        return ("NAO sobrevive ao desconto da composicao: pode ser efeito mecanico do n de "
                "itens e nao sustenta 'a busca antecipa a demanda'")
    if robustez_digna:
        return ("negativo na primaria; a robustez passou e NAO resgata nada - descritivo, "
                "hipotese para trabalho futuro")
    return "negativo"


def medir_na_faixa(M, Y, n_perm: int, semente: int) -> dict:
    """Curva `0..14`, a estatística da faixa e o nulo do máximo na mesma faixa."""
    curva = curva_de_lags(M, Y)
    obs = estatistica_na_faixa(curva)
    nulos = permutacao_p2(M, Y, n=n_perm, semente=semente, lags=LAGS_EXPERIMENTO_2)
    if not len(nulos) or np.isnan(obs["valor"]):
        return {"curva": curva.to_dict("records"), **obs, "digno": False, "nulo_vazio": True}
    corte = float(np.percentile(nulos, PERCENTIL_CORTE))
    dp = float(np.std(nulos))
    return {
        "curva": curva.to_dict("records"),
        **obs,
        "termos_no_painel": int(M.shape[0]),
        "n_permutacoes_efetivas": int(len(nulos)),
        "nulo_mediana": float(np.median(nulos)),
        "nulo_p95": corte,
        "p_empirico": float((nulos >= obs["valor"]).mean()),
        "z": (obs["valor"] - float(np.mean(nulos))) / dp if dp else float("nan"),
        # R8d.5: acima do p95 do próprio nulo, com o lag na faixa (a faixa já garante k >= 1)
        "digno": bool(obs["valor"] > corte and obs["lag"] is not None),
    }


def rodar_experimento_2(mom: pd.DataFrame, alvo: pd.DataFrame,
                        n_perm: int = N_PERMUTACOES, semente: int = SEMENTE_EXP2) -> dict:
    """O experimento 2 inteiro, sobre o momentum da primária (B) já calculado.

    Recebe os dados prontos para poder ser exercitado com caso sintético; a leitura do
    Trends e do Bronze fica no `_main`.
    """
    m = mom.dropna(subset=["momentum"]).copy()
    m["dia"] = pd.to_datetime(m["dia"])
    m = m[m["dia"] >= PRIMEIRO_DIA_DE_BUSCA_EXP2]
    if m.empty:
        raise ValueError("nenhum momentum de busca posterior a "
                         f"{ULTIMO_DIA_DE_BUSCA}: o dado do experimento 2 nao existe")
    # A janela da venda que pode parear com esse momentum em algum lag da grade 0..14.
    a = alvo.copy()
    a["dia"] = pd.to_datetime(a["dia"])
    duplicados = int(a.duplicated(["termo", "dia"]).sum())
    if duplicados:
        # O ajuste da composição (R8e.1) veria o mesmo termo-dia duas vezes e o painel
        # ficaria com a última: o resultado dependeria da ordem das linhas.
        raise ValueError(f"alvo com {duplicados} termo-dia(s) duplicado(s): nada foi medido")
    inicio, fim = m["dia"].min(), m["dia"].max() + pd.to_timedelta(max(LAGS), unit="D")
    a = alvo_sem_composicao(a[(a["dia"] >= inicio) & (a["dia"] <= fim)])

    series = [c for c in ALVOS if c in a.columns] + \
             [c for c in ALVOS_ROBUSTEZ_COMPOSICAO if c in a.columns]
    resultado: dict = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(),
        "carater": "EXPERIMENTO 2 - confirmatorio pre-registrado (protocolo §8d e §8e)",
        "fontes_do_alvo": fontes_do_alvo(a),
        "primaria": f"{PRIMARIA_EXPERIMENTO_2}|{ALVO_PRIMARIO}",
        "faixa_de_lag": list(FAIXA_LAG_EXPERIMENTO_2),
        "janela_de_busca": [str(inicio.date()), str(m["dia"].max().date())],
        "janela_de_venda": [str(inicio.date()), str(fim.date())],
        "minimo_pares_por_termo": MINIMO_PARES_POR_TERMO,
        "n_permutacoes": n_perm,
        "semente": semente,
        "desconto_composicao": DESCONTO_COMPOSICAO,
        "series": {},
    }
    for coluna in series:
        M, Y, _termos, _dias = montar_painel(m, a, coluna)
        resultado["series"][coluna] = medir_na_faixa(M, Y, n_perm, semente)

    # P1: lags invertidos, só na primária (protocolo §5)
    M, Y, _t, _d = montar_painel(m, a, ALVO_PRIMARIO)
    resultado["placebo_p1_lags_invertidos"] = \
        curva_de_lags(M, Y, lags=LAGS_PLACEBO_INVERTIDO).to_dict("records")

    prim = resultado["series"].get(ALVO_PRIMARIO, {}).get("digno", False)
    rob = resultado["series"].get("alvo_unificado_sem_composicao", {}).get("digno", False)
    resultado["primaria_digna"] = bool(prim)
    resultado["robustez_composicao_digna"] = bool(rob)
    resultado["veredito"] = veredito_experimento_2(prim, rob)
    return resultado


def _main_experimento_2() -> None:
    """Um disparo só: sem --rapido (rodar rápido também é olhar o dado) e sem sobrescrever."""
    if "--rapido" in sys.argv:
        raise SystemExit("RECUSADO: o experimento 2 nao tem modo rapido - rodar e olhar.")
    destino = RAIZ / "02_Dados" / ARTEFATO_EXP2
    if destino.exists():
        raise SystemExit(f"RECUSADO: {destino.name} ja existe. O experimento 2 roda UMA vez;\n"
                         "   rodar de novo seria escolher entre execucoes pelo resultado.")
    from alvo_h1 import construir_alvo

    trends = carregar_trends()
    cond = condicao_experimento_2(trends)
    print(f"  condicao da §1: {cond['termos_com_dias_suficientes']} termos com >= "
          f"{cond['dias_exigidos']} dias de busca desde {cond['primeiro_dia_de_busca']} "
          f"(exige {cond['termos_exigidos']})")
    if not cond["cumprida"]:
        raise SystemExit("A condicao da §1 NAO se cumpre: o experimento 2 nao roda.")
    # §8h (20/10): sem o ML, declarado aqui mesmo sendo o padrão, para que a execução não
    # dependa do valor padrão do `construir_alvo` no dia em que isto rodar.
    alvo = construir_alvo(com_mercado_livre=False)["alvo"]
    conferir_composicao_experimento_2(alvo)
    r = rodar_experimento_2(momentum(trends, PRIMARIA_EXPERIMENTO_2), alvo)
    r["condicao_secao_1"] = cond

    print(f"\n=== EXPERIMENTO 2 — {r['primaria']}, faixa {r['faixa_de_lag']} ===")
    print(f"  busca {r['janela_de_busca']} · venda {r['janela_de_venda']} · "
          f"fontes {' + '.join(r['fontes_do_alvo'])}")
    print(f"  {'serie':34s} {'termos':>6s} {'lag':>4s} {'observado':>10s} {'nulo p95':>9s} "
          f"{'p emp':>7s} {'z':>6s}  digno")
    for coluna, s in r["series"].items():
        if s.get("nulo_vazio"):
            print(f"  {coluna:34s}  (sem painel)")
            continue
        print(f"  {coluna:34s} {s['termos_no_painel']:6d} {s['lag']:4d} {s['valor']:+10.4f} "
              f"{s['nulo_p95']:+9.4f} {s['p_empirico']:7.3f} {s['z']:+6.2f}  {s['digno']}")
    print(f"\n  VEREDITO (R8e.3): {r['veredito']}")
    _gravar_fail_closed(destino, json.dumps(r, indent=1, ensure_ascii=False), r["fontes_do_alvo"])
    print(f"  artefato: {destino.relative_to(RAIZ)}")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def comparar_combinacoes(
    n_perm: int = 200, semente: int = 20260908, com_mercado_livre: bool = True,
    com_regras_artes: bool = True,
) -> pd.DataFrame:
    """Cada combinação (operacionalização × alvo) contra o seu próprio nulo.

    Isto não faz parte do pré-registro. É análise exploratória posterior (08/09), feita
    para comparar as combinações possíveis, e não altera a primária, que continua sendo
    `A_media_movel` sobre `alvo_unificado` com 1.000 permutações. O experimento inteiro já
    é exploratório, então a análise é legítima; lida como parte do pré-registro, porém,
    seria garimpo, e por isso a distinção está escrita aqui e não só no relatório.

    Por que comparar os valores brutos entre combinações é errado: cada combinação tem um
    painel diferente (nº de termos, nº de pares por termo), e o nível de fundo depende
    disso. Um ρ de +0,22 num painel de 76 termos e um de +0,07 num de 128 não estão na
    mesma unidade. Além disso, o maior de 135 células (9 combinações × 15 lags) é, por
    construção, o máximo de uma busca; comparar máximos sem nulo compara números de bases
    diferentes.

    A unidade comparável é o quanto cada uma sobe acima do próprio envelope: o
    `p_empirico` (fração das permutações cujo máximo iguala ou supera o observado) e o
    `z_empirico` ((observado − média do nulo) / desvio do nulo). Nos dois, o painel sai da
    conta, e é isso que os torna comparáveis.
    """
    from alvo_h1 import construir_alvo

    trends = carregar_trends()
    alvo = construir_alvo(com_mercado_livre=com_mercado_livre,
                          com_regras_artes=com_regras_artes)["alvo"]
    presentes = [c for c in ALVOS if c in alvo.columns]
    linhas = []
    for qual in OPERACIONALIZACOES:
        mom = momentum(trends, qual)
        for coluna in presentes:
            M, Y, termos, _ = montar_painel(mom, alvo, coluna)
            obs = estatistica_primaria(curva_de_lags(M, Y))
            nulos = permutacao_p2(M, Y, n=n_perm, semente=semente)
            if not len(nulos) or np.isnan(obs["valor"]):
                continue
            dp = float(np.std(nulos))
            linhas.append({
                "operacionalizacao": qual,
                "alvo": coluna,
                "termos": len(termos),
                "lag": obs["lag"],
                "observado": obs["valor"],
                "nulo_mediana": float(np.median(nulos)),
                "nulo_p95": float(np.percentile(nulos, PERCENTIL_CORTE)),
                "p_empirico": float((nulos >= obs["valor"]).mean()),
                "z_empirico": (obs["valor"] - float(np.mean(nulos))) / dp if dp else float("nan"),
                "acima_do_p95": bool(obs["valor"] > float(np.percentile(nulos, PERCENTIL_CORTE))),
            })
    return pd.DataFrame(linhas).sort_values("p_empirico").reset_index(drop=True)


def rodar(rapido: bool = False, com_mercado_livre: bool = True,
          com_regras_artes: bool = True) -> dict:
    from alvo_h1 import construir_alvo

    trends = carregar_trends()
    alvo = construir_alvo(com_mercado_livre=com_mercado_livre,
                          com_regras_artes=com_regras_artes)["alvo"]
    fontes = fontes_do_alvo(alvo)
    presentes = [c for c in ALVOS if c in alvo.columns]

    resultado: dict = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(),
        "carater": "EXPLORATORIO - gera hipotese, nao confirma (protocolo §1)",
        # Declarado no artefato para que ele não seja confundido com o de outra
        # composição; é o campo que o gravador fail-closed consulta.
        "fontes_do_alvo": fontes,
        "minimo_pares_por_termo": MINIMO_PARES_POR_TERMO,
        "n_permutacoes": N_PERMUTACOES if not rapido else 50,
        "curvas": {},
        "primarias": {},
    }

    for qual in OPERACIONALIZACOES:
        mom = momentum(trends, qual)
        for coluna in presentes:
            M, Y, termos, _dias = montar_painel(mom, alvo, coluna)
            curva = curva_de_lags(M, Y)
            chave = f"{qual}|{coluna}"
            resultado["curvas"][chave] = curva.to_dict("records")
            resultado["primarias"][chave] = {
                **estatistica_primaria(curva),
                "termos_no_painel": len(termos),
            }

    # --- placebos, só na primária (protocolo §5) ---
    mom_p = momentum(trends, PRIMARIA)
    M, Y, termos, _ = montar_painel(mom_p, alvo, ALVO_PRIMARIO)
    obs = estatistica_primaria(curva_de_lags(M, Y))

    p1 = curva_de_lags(M, Y, lags=LAGS_PLACEBO_INVERTIDO)
    resultado["placebo_p1_lags_invertidos"] = p1.to_dict("records")

    n_perm = 50 if rapido else N_PERMUTACOES
    nulos = permutacao_p2(M, Y, n=n_perm)
    corte = float(np.percentile(nulos, PERCENTIL_CORTE)) if len(nulos) else float("nan")
    resultado["placebo_p2"] = {
        "n_permutacoes_efetivas": int(len(nulos)),
        "percentil_corte": PERCENTIL_CORTE,
        "corte": corte,
        "observado": obs["valor"],
        "lag_observado": obs["lag"],
        "acima_do_corte": bool(obs["valor"] > corte) if len(nulos) else None,
        "p_empirico": float((nulos >= obs["valor"]).mean()) if len(nulos) else None,
        "nulo_mediana": float(np.median(nulos)) if len(nulos) else None,
    }
    resultado["digno_de_replicacao"] = bool(
        len(nulos)
        and obs["valor"] > corte
        and obs["lag"] is not None
        and obs["lag"] >= LAG_MINIMO_PRIMARIA
    )
    return resultado


def _rotulo_pedido() -> str | None:
    if "--rotulo" in sys.argv:
        i = sys.argv.index("--rotulo")
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        raise SystemExit("--rotulo exige um nome (ex.: --rotulo reanalise_3fontes)")
    return None


def _main() -> None:
    if "--experimento-2" in sys.argv:
        _main_experimento_2()
        return
    rotulo = _rotulo_pedido()
    com_ml = "--duas-fontes" not in sys.argv
    # 30/09: o classificador ganhou a regra de Artes. O experimento 1 e a reanálise
    # usaram a versão anterior; reproduzi-los exige esta chave (§8f do protocolo).
    com_artes = "--sem-regras-artes" not in sys.argv

    if "--comparar" in sys.argv:
        n_comb = len(OPERACIONALIZACOES) * (len(ALVOS) if com_ml else len(ALVOS) - 1)
        print(f"=== COMPARACAO das {n_comb} combinacoes, cada uma contra o SEU nulo ===")
        print("  (analise exploratoria POSTERIOR ao pre-registro; nao altera a primaria)\n")
        tab = comparar_combinacoes(com_mercado_livre=com_ml, com_regras_artes=com_artes)
        cab = (f"  {'operacionalizacao':16s} {'alvo':16s} {'term':>5s} {'lag':>4s} "
               f"{'observado':>10s} {'nulo p50':>9s} {'nulo p95':>9s} {'p emp':>7s} {'z':>6s}")
        print(cab)
        print("  " + "-" * (len(cab) - 2))
        for _, l in tab.iterrows():
            marca = "  <= acima do p95" if l["acima_do_p95"] else ""
            print(f"  {l['operacionalizacao']:16s} {l['alvo']:16s} {int(l['termos']):5d} "
                  f"{int(l['lag']):4d} {l['observado']:+10.4f} {l['nulo_mediana']:+9.4f} "
                  f"{l['nulo_p95']:+9.4f} {l['p_empirico']:7.3f} {l['z_empirico']:+6.2f}{marca}")
        destino = _destino("comparacao_lead_lag_h1.csv", rotulo)
        if destino.exists() and not rotulo:
            raise SystemExit(
                f"\nRECUSADO: {destino.name} ja existe e o CSV nao carrega a composicao\n"
                f"   das fontes. → use --rotulo <nome> para nao apagar a comparacao anterior.\n"
            )
        tab.to_csv(destino, index=False)
        print(f"\n  quantas passam do proprio p95: {int(tab['acima_do_p95'].sum())} de {len(tab)}")
        print(f"  artefato: {destino.relative_to(RAIZ)}")
        return

    rapido = "--rapido" in sys.argv
    r = rodar(rapido=rapido, com_mercado_livre=com_ml, com_regras_artes=com_artes)
    print(f"  fontes do alvo: {' + '.join(r['fontes_do_alvo'])}\n")

    print("=== EXPERIMENTO 1 — lead-lag da H1 ===")
    print(f"  carater: {r['carater']}")
    print(f"  minimo de pares por termo: {r['minimo_pares_por_termo']} (emenda E8.1)\n")

    print("--- ESTATISTICA PRIMARIA por (operacionalizacao | alvo) ---")
    print(f"  {'combinacao':40s} {'termos':>7s} {'lag':>5s} {'mediana rho':>12s}")
    for chave, v in r["primarias"].items():
        marca = " <= PRIMARIA" if chave == f"{PRIMARIA}|{ALVO_PRIMARIO}" else ""
        lag = "-" if v["lag"] is None else str(v["lag"])
        print(f"  {chave:40s} {v['termos_no_painel']:7d} {lag:>5s} "
              f"{v['valor']:12.4f}{marca}")

    print("\n--- A CURVA DA PRIMARIA, lag a lag ---")
    curva = pd.DataFrame(r["curvas"][f"{PRIMARIA}|{ALVO_PRIMARIO}"])
    for _, l in curva.iterrows():
        marca = "  (k=0: benchmark Choi & Varian)" if l["lag"] == 0 else ""
        print(f"   k={int(l['lag']):3d}  termos {int(l['termos']):3d}  "
              f"mediana {l['mediana_rho']:+.4f}  "
              f"positivos {l['fracao_positiva']:.1%}{marca}")

    print("\n--- PLACEBO P1: lags INVERTIDOS (a venda antecedendo a busca) ---")
    for l in r["placebo_p1_lags_invertidos"]:
        print(f"   k={int(l['lag']):3d}  termos {int(l['termos']):3d}  "
              f"mediana {l['mediana_rho']:+.4f}  positivos {l['fracao_positiva']:.1%}")

    p2 = r["placebo_p2"]
    print(f"\n--- PLACEBO P2: alvo embaralhado, {p2['n_permutacoes_efetivas']} permutacoes ---")
    print(f"   observado ............. {p2['observado']:+.4f} (lag {p2['lag_observado']})")
    print(f"   mediana sob o nulo .... {p2['nulo_mediana']:+.4f}")
    print(f"   corte p{p2['percentil_corte']} ............. {p2['corte']:+.4f}")
    print(f"   p empirico ............ {p2['p_empirico']:.4f}")
    print(f"\n   DIGNO DE REPLICACAO: {r['digno_de_replicacao']}"
          "   (criterio do protocolo §5; NAO e confirmacao)")

    if not rapido:
        destino = _destino("resultado_lead_lag_h1.json", rotulo)
        _gravar_fail_closed(
            destino, json.dumps(r, indent=1, ensure_ascii=False), r["fontes_do_alvo"]
        )
        print(f"\n  artefato: {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    _main()
