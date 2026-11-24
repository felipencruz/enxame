"""A receita v3 do Mercado Livre: o selo do rank e os campos essenciais.

Por que este arquivo existe
---------------------------
Em 23/09 o projeto decidiu que o coletor do ML passaria a gravar o rank, como o da
Amazon. A medição de 24/09 (`sondas/sonda_rank_ml.py`, artefato
`02_Dados/raw/sonda_rank_ml_20260924/`) encontrou dois sinais em cada slide: a posição
(`aria-label "k de M"`, no próprio slide, fora do alcance da receita, que só busca
descendentes) e o selo "Nº MAIS VENDIDO" (descendente, com lacunas na numeração). A v3
acrescenta o selo e declara `titulo`, `preco` e `link` como essenciais. A posição é
numerada pelo coletor do n8n, o que evita recriar o container da API.

O que se fixa aqui, contra os dois HTML versionados (29/07 e 24/09):
  - a regressão campo a campo: os seis campos antigos saem idênticos aos da v2, item a item;
  - o selo existe em todo slide, cresce dentro do carrossel e nunca fica abaixo da posição;
  - a v3 nunca é mais branda que a v2: um campo novo a 100% sobe a média e dilui a perda
    dos antigos. Medido: 7 combinações de defeito que a v2 reprova passariam na v3 sem os
    essenciais. Este teste impede que os essenciais sejam removidos só porque a nota subiu.
"""

import itertools
import json
import re
from pathlib import Path

import pytest

from app import coletor
from app.agentes import analista_estrutura as ae

RAIZ = Path(__file__).resolve().parent.parent.parent
RECEITAS = Path(__file__).resolve().parent.parent / "receitas" / "www.mercadolivre.com.br"
V2 = RECEITAS / "receita_20260715_045658.json"
V3 = RECEITAS / "receita_20260925_000039.json"
HTMLS = {
    "29/07": (RAIZ / "02_Dados/raw/sonda_reabertura_ml_20260729/20260729T020816Z_ml_mais-vendidos_EnxameBot.html", 162),
    "24/09": (RAIZ / "02_Dados/raw/sonda_rank_ml_20260924/20260924T235228Z_ml_mais-vendidos_EnxameBot.html", 180),
}
ANTIGOS = ("categoria", "titulo", "preco", "preco_antigo", "desconto", "link")
_SELO = re.compile(r"^\s*(\d+)\s*º\s*MAIS VENDIDO\s*$")


def _ler(caminho: Path) -> str:
    if not caminho.exists():  # pragma: no cover
        pytest.skip(f"artefato versionado ausente: {caminho}")
    return caminho.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def v2() -> dict:
    return json.loads(_ler(V2))


@pytest.fixture(scope="module")
def v3() -> dict:
    return json.loads(_ler(V3))


@pytest.mark.parametrize("dia", list(HTMLS))
def test_v3_extrai_os_seis_campos_antigos_identicos_a_v2(v2, v3, dia):
    """Regressão antes de trocar a receita: mesma página, mesmos itens, mesmos valores,
    campo a campo, item a item."""
    caminho, n = HTMLS[dia]
    html = _ler(caminho)
    antigas, novas = ae.aplicar_receita(html, v2), ae.aplicar_receita(html, v3)
    assert len(antigas) == len(novas) == n
    for a, b in zip(antigas, novas):
        assert {c: a.get(c) for c in ANTIGOS} == {c: b.get(c) for c in ANTIGOS}


@pytest.mark.parametrize("dia", list(HTMLS))
def test_selo_em_todo_slide_crescente_e_nunca_abaixo_da_posicao(v3, dia):
    """O selo é o rank declarado: cresce no carrossel e pula posições (lacunas), então é sempre
    maior ou igual à posição. Por isso não serve à fórmula do percentil, que usa a posição."""
    caminho, _ = HTMLS[dia]
    linhas = ae.aplicar_receita(_ler(caminho), v3)
    por_carrossel: dict[str, list[int]] = {}
    for linha in linhas:
        m = _SELO.match(linha.get("selo_mais_vendido") or "")
        assert m, f"selo ilegível: {linha.get('selo_mais_vendido')!r}"
        por_carrossel.setdefault(linha["categoria"], []).append(int(m.group(1)))
    buracos = 0
    for selos in por_carrossel.values():
        assert all(b > a for a, b in zip(selos, selos[1:])), "o selo tem de crescer no carrossel"
        assert all(s >= k for k, s in enumerate(selos, start=1)), "o selo nunca fica abaixo da posição"
        buracos += sum(s != k for k, s in enumerate(selos, start=1))
    assert buracos > 0, "sem buracos o selo seria a posição — a medição de 24/09 diz que não é"


@pytest.mark.parametrize("dia", list(HTMLS))
def test_v3_aprovada_nas_duas_paginas(v3, dia):
    caminho, n = HTMLS[dia]
    linhas = ae.aplicar_receita(_ler(caminho), v3)
    validacao = ae.validar_receita(linhas, coletor._campos_da_receita(v3))
    assert validacao["itens_encontrados"] == n
    assert validacao["campos"]["selo_mais_vendido"]["taxa"] == 1.0
    assert ae.aprovada(validacao, v3) is True


def test_v3_declara_os_essenciais_que_ele_decidiu(v3):
    assert ae.campos_essenciais(v3) == {"titulo", "preco", "link"}


def _validacao(taxas: dict[str, float]) -> dict:
    return {
        "itens_encontrados": 180,
        "campos": {k: {"taxa": t, "taxa_valida": t, "tipo": None} for k, t in taxas.items()},
    }


def test_v3_nunca_aprova_o_que_a_v2_reprova(v2, v3):
    """Proteção contra a diluição da régua. Partindo das taxas medidas em 24/09, zera cada
    combinação de campos antigos exceto `titulo` e exige: se a v2 reprova, a v3 também reprova.

    Sem os essenciais, 7 destas combinações passariam na v3 (é o controle abaixo); isso
    mostra que o teste detecta o defeito, e não só que passa."""
    base = {"categoria": 1.0, "titulo": 1.0, "preco": 1.0, "preco_antigo": 0.767,
            "desconto": 0.767, "link": 1.0}
    outros = [c for c in ANTIGOS if c != "titulo"]
    v3_sem_essenciais = json.loads(json.dumps(v3))
    del v3_sem_essenciais["_meta"]["campos_essenciais"]
    diluidas = 0
    for r in range(1, len(outros) + 1):
        for perdidos in itertools.combinations(outros, r):
            taxas = {k: (0.0 if k in perdidos else v) for k, v in base.items()}
            if ae.aprovada(_validacao(taxas), v2):
                continue
            com_selo = _validacao({**taxas, "selo_mais_vendido": 1.0})
            assert ae.aprovada(com_selo, v3) is False, f"a v3 aprovaria a perda de {perdidos}"
            diluidas += int(ae.aprovada(com_selo, v3_sem_essenciais))
    assert diluidas == 7, "o controle: sem os essenciais, a diluição medida em 24/09 reaparece"
