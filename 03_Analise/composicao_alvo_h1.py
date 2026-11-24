# -*- coding: utf-8 -*-
"""A série diária do alvo carrega composição? (opção C da análise de 24/09)

Motivação
---------
O alvo de cada termo num dia é a média dos percentis dos seus itens (regra 6 do alvo,
em `alvo_h1`). Medido em 24/09: dentro de cada termo, ao longo dos dias, o alvo cai
quando o termo ganha itens (Amazon, mediana −0,30 por termo), porque item novo entra
embaixo e puxa a média; com o máximo no lugar da média o efeito inverte. A H1 compara
cada termo consigo mesmo no tempo, então esse componente mecânico pode fabricar ou
esconder lead-lag se o número de itens andar junto com a busca defasada.

Esta análise responde as duas perguntas com as funções oficiais do runner
(`montar_painel`, `correlacoes_por_termo`), para a resposta sair na mesma régua da H1:

  (1) Elo: a busca defasada antecipa o número de itens do termo? O mesmo teste da H1,
      com `n_itens_*` no lugar do alvo, e o placebo P2 (pareamento termo-termo
      embaralhado).
  (2) Efeito: a curva da H1 muda quando o número de itens é descontado dentro de cada
      termo? Cada versão é medida contra o próprio nulo, porque o N difere entre elas.

A estatística é a do experimento 2 (§8d): `max_k mediana(ρ_k)` na faixa `8..12`, com o
nulo do máximo na mesma faixa; e, ao lado, a do experimento 1 (máximo em `1..14`), para
comparação.

Limite: não é o experimento 2 nem altera o pré-registro. A medição de 24/09 rodou sobre o
dado do experimento 1 (Trends até 06/09). Hoje `carregar_trends` junta as três janelas, então
a mesma chamada lê o Trends até 19/10 e o alvo até 01/11, com o Mercado Livre até 06/10: os
números não reproduzem os de 24/09. É exploratório e nenhum número daqui é resultado da H1.

Rodar: `.venv/Scripts/python 03_Analise/composicao_alvo_h1.py [--permutacoes N] [saida.json]`
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from experimento_lead_lag_h1 import correlacoes_por_termo, montar_painel  # noqa: E402
from momentum_busca import carregar_trends, momentum  # noqa: E402
from protocolo_lead_lag_h1 import (  # noqa: E402
    LAG_MINIMO_PRIMARIA,
    LAGS,
    LAGS_EXPERIMENTO_2,
    MINIMO_PARES_POR_TERMO,
    OPERACIONALIZACOES,
    PERCENTIL_CORTE,
    PRIMARIA_EXPERIMENTO_2,
)

FONTES = ("shopee", "amazon", "ml")
LAGS_EXP1 = tuple(k for k in LAGS if k >= LAG_MINIMO_PRIMARIA)


def descontar_composicao(alvo: pd.DataFrame, fonte: str) -> pd.Series:
    """Resíduo, dentro de cada termo, da regressão linear do alvo da fonte no seu nº de itens.

    Dentro do termo, e não no painel: o que se quer tirar é a variação do dia a dia que vem de o
    termo ter mais ou menos itens naquele dia, não a diferença entre termos, que a correlação
    por termo da H1 já ignora. Termo sem variação no nº de itens fica com o alvo centrado.
    """
    y, n = alvo[f"alvo_{fonte}"], alvo[f"n_itens_{fonte}"].astype(float)
    fora = pd.Series(np.nan, index=alvo.index)
    validos = y.notna() & n.notna()
    for _, idx in alvo[validos].groupby("termo").groups.items():
        yy, nn = y.loc[idx].to_numpy(float), n.loc[idx].to_numpy(float)
        nc = nn - nn.mean()
        beta = (nc * (yy - yy.mean())).sum() / (nc * nc).sum() if (nc * nc).sum() > 0 else 0.0
        fora.loc[idx] = yy - yy.mean() - beta * nc
    return fora


def _mediana_por_lag(M, Y, lags) -> dict[int, float]:
    out = {}
    for k in lags:
        rho = correlacoes_por_termo(M, Y, k, MINIMO_PARES_POR_TERMO)
        bons = rho[~np.isnan(rho)]
        out[k] = float(np.median(bons)) if len(bons) else float("nan")
    return out


def _maximo(medianas: dict[int, float], lags) -> tuple[float, int | None]:
    vals = [(medianas[k], k) for k in lags if not np.isnan(medianas[k])]
    return max(vals) if vals else (float("nan"), None)


def medir(M, Y, n_perm: int, semente: int) -> dict:
    """Curva 0..14, as duas estatísticas e o nulo de cada uma pela mesma permutação."""
    curva = _mediana_por_lag(M, Y, LAGS)
    obs2, lag2 = _maximo(curva, LAGS_EXPERIMENTO_2)
    obs1, lag1 = _maximo(curva, LAGS_EXP1)
    rng = np.random.default_rng(semente)
    n_termos = M.shape[0]
    nulo1, nulo2 = [], []
    for _ in range(n_perm):
        med = _mediana_por_lag(M, Y[rng.permutation(n_termos)], LAGS_EXP1)
        nulo1.append(_maximo(med, LAGS_EXP1)[0])
        nulo2.append(_maximo(med, LAGS_EXPERIMENTO_2)[0])
    nulo1, nulo2 = np.array(nulo1), np.array(nulo2)

    def _contra(obs, nulo):
        nulo = nulo[~np.isnan(nulo)]
        dp = float(nulo.std()) if len(nulo) else float("nan")
        return {
            "observado": obs,
            "nulo_mediana": float(np.median(nulo)),
            "nulo_p95": float(np.percentile(nulo, PERCENTIL_CORTE)),
            "p_empirico": float((nulo >= obs).mean()),
            "z": (obs - float(nulo.mean())) / dp if dp else float("nan"),
        }

    return {
        "termos": int(n_termos),
        "curva": {str(k): round(v, 4) for k, v in curva.items()},
        "faixa_8_12": {"lag": lag2, **_contra(obs2, nulo2)},
        "grade_1_14": {"lag": lag1, **_contra(obs1, nulo1)},
    }


def rodar(n_perm: int = 1000, semente: int = 20260924) -> dict:
    from alvo_h1 import construir_alvo

    # Explícito, porque o padrão do `construir_alvo` não inclui o ML desde 20/10. Esta
    # medição (24/09) foi feita sobre as três fontes, e é assim que se reproduz.
    alvo = construir_alvo(com_mercado_livre=True)["alvo"].copy()
    presentes = [f for f in FONTES if f"n_itens_{f}" in alvo.columns]
    alvo["n_itens_total"] = alvo[[f"n_itens_{f}" for f in presentes]].sum(axis=1, min_count=1)
    for f in presentes:
        alvo[f"alvo_{f}_sem_composicao"] = descontar_composicao(alvo, f)

    trends = carregar_trends()
    saida: dict = {"n_permutacoes": n_perm, "semente": semente, "elo": {}, "efeito": {}}
    for qual in OPERACIONALIZACOES:
        mom = momentum(trends, qual)
        saida["elo"][qual] = {}
        for coluna in [f"n_itens_{f}" for f in presentes] + ["n_itens_total"]:
            M, Y, _t, _d = montar_painel(mom, alvo, coluna)
            saida["elo"][qual][coluna] = medir(M, Y, n_perm, semente)
            print(f"[elo] {qual} × {coluna}: feito", flush=True)
        if qual != PRIMARIA_EXPERIMENTO_2:
            continue
        for f in presentes:
            for coluna in (f"alvo_{f}", f"alvo_{f}_sem_composicao"):
                M, Y, _t, _d = montar_painel(mom, alvo, coluna)
                saida["efeito"][coluna] = medir(M, Y, n_perm, semente)
                print(f"[efeito] {qual} × {coluna}: feito", flush=True)
    return saida


if __name__ == "__main__":
    n = 1000
    if "--permutacoes" in sys.argv:
        n = int(sys.argv[sys.argv.index("--permutacoes") + 1])
    destino = next((a for a in sys.argv[1:] if a.endswith(".json")), None)
    resultado = rodar(n)
    texto = json.dumps(resultado, ensure_ascii=False, indent=1)
    if destino:
        Path(destino).write_text(texto, encoding="utf-8")
        print(f"gravado em {destino}")
    else:
        print(texto)
