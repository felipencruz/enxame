"""A receita v4 do Mercado Livre: a fonte trocou o layout e o Agente 4 reparou.

Por que este arquivo existe
---------------------------
Em 25/09/2026, entre 06:00 e 12:00 BRT, o ML trocou a marcação da página de mais vendidos
(`dynamic-carousel` -> `poly-card` / `sbc-products-carousel`) e a v3 passou a extrair 0 itens.
O reparo pelo Agente 4 passou por um portão antes de entrar em produção: duas passadas
isoladas sobre o HTML guardado (`sondas/sonda_reparo_layout_ml.py`, artefato
`02_Dados/raw/layout_ml_20260925/`). A 1ª achou os produtos e perdeu a categoria em 100%,
e a régua da v3 a aprovaria. A 2ª, com a descrição do campo apontando o link "Ver mais",
acertou. A v4 é a 2ª passada unida aos seletores da v3 (lista "antigo, novo"), com a
categoria vinda do `href` desse link nos dois layouts.

O que se fixa aqui, contra os três HTML versionados (29/07, 24/09 e 25/09):
  - regressão campo a campo: no layout antigo a v4 extrai o mesmo que a v3, exceto a
    categoria, que passa a ser o link e tem de levar ao mesmo nome pelo mapa do
    `Achatar Produtos`;
  - no layout novo: 195 itens em 10 carrosséis, todos com categoria;
  - `categoria` é essencial: a candidata da 1ª passada (categoria em 0%) é reprovada pela
    v4, e seria aprovada sem isso. É o caso, num reparo real, de um campo não essencial
    perdido por inteiro e compensado pela média dos outros.
"""

import json
import re
from pathlib import Path

import pytest

from app import coletor
from app.agentes import analista_estrutura as ae

RAIZ = Path(__file__).resolve().parent.parent.parent
RECEITAS = Path(__file__).resolve().parent.parent / "receitas" / "www.mercadolivre.com.br"
V3 = RECEITAS / "receita_20260925_000039.json"
V4 = RECEITAS / "receita_20260925_154603.json"
PROVA = RAIZ / "02_Dados/raw/layout_ml_20260925"
ANTIGOS = {
    "29/07": RAIZ / "02_Dados/raw/sonda_reabertura_ml_20260729/20260729T020816Z_ml_mais-vendidos_EnxameBot.html",
    "24/09": RAIZ / "02_Dados/raw/sonda_rank_ml_20260924/20260924T235228Z_ml_mais-vendidos_EnxameBot.html",
}
NOVO = PROVA / "20260925T1504Z_ml_mais-vendidos_EnxameBot.html"
# O mesmo mapa do `Achatar Produtos` do n8n, conferido nos HTML de 29/07 e 24/09.
MAPA = {
    "MLB1144": "Games", "MLB5726": "Eletrodomésticos", "MLB263532": "Ferramentas",
    "MLB1246": "Beleza e Cuidado Pessoal", "MLB1051": "Celulares e Telefones",
    "MLB1648": "Informática", "MLB1000": "Eletrônicos, Áudio e Vídeo",
    "MLB1276": "Esportes e Fitness", "MLB1430": "Calçados, Roupas e Bolsas",
    "MLB5672": "Acessórios para Veículos",
}


def _ler(caminho: Path) -> str:
    if not caminho.exists():  # pragma: no cover
        pytest.skip(f"artefato versionado ausente: {caminho}")
    return caminho.read_text(encoding="utf-8", errors="replace")


def _id(href: str | None) -> str | None:
    m = re.search(r"/mais-vendidos/(MLB\d+)", href or "")
    return m.group(1) if m else None


@pytest.fixture(scope="module")
def v3() -> dict:
    return json.loads(_ler(V3))


@pytest.fixture(scope="module")
def v4() -> dict:
    return json.loads(_ler(V4))


@pytest.mark.parametrize("dia", list(ANTIGOS))
def test_v4_no_layout_antigo_extrai_o_mesmo_que_a_v3(v3, v4, dia):
    html = _ler(ANTIGOS[dia])
    a, b = ae.aplicar_receita(html, v3), ae.aplicar_receita(html, v4)
    assert len(a) == len(b) > 0
    for x, y in zip(a, b):
        for campo in ("titulo", "preco", "preco_antigo", "desconto", "link", "selo_mais_vendido"):
            assert x[campo] == y[campo], (dia, campo)
        # a categoria vira o link "Ver mais", e o mapa devolve o nome que o h2 dava
        assert MAPA[_id(y["categoria"])] == x["categoria"], dia


def test_v4_no_layout_novo_acha_os_195_itens_nos_10_carrosseis(v4):
    linhas = ae.aplicar_receita(_ler(NOVO), v4)
    assert len(linhas) == 195
    ids = [_id(x["categoria"]) for x in linhas]
    assert None not in ids
    assert set(ids) == set(MAPA)
    assert all(x["titulo"] and x["preco"] and x["link"] for x in linhas)


def test_v3_extrai_zero_no_layout_novo(v3):
    """O defeito que motivou a v4: o layout novo zera a extração da v3."""
    assert ae.aplicar_receita(_ler(NOVO), v3) == []


def test_categoria_essencial_reprova_a_candidata_que_a_perdeu(v3, v4):
    candidata = json.loads(_ler(PROVA / "20260925_reparo_agente4_candidata.json"))
    campos = coletor._campos_da_receita(v3)
    val = ae.validar_receita(ae.aplicar_receita(_ler(NOVO), candidata), campos)
    assert val["campos"]["categoria"]["taxa"] == 0.0
    # com os essenciais da v3 ela passaria, pois a média dos outros campos a sustenta ...
    assert ae.aprovada(val, {"_meta": {"campos_essenciais": v3["_meta"]["campos_essenciais"]}})
    # ... e com os da v4 não passa
    assert "categoria" in v4["_meta"]["campos_essenciais"]
    assert not ae.aprovada(val, v4)


def test_v4_e_a_receita_que_o_coletor_carrega(v4):
    assert v4["_meta"]["aprovada"] is True
    assert coletor.carregar_receita_mais_recente.__doc__  # a função existe
    maior = sorted(RECEITAS.glob("receita_*.json"))[-1]
    assert maior.name == V4.name
