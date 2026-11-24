"""A rota atual da Amazon (22 vitrines) contra HTML versionado.

Por que este arquivo existe
---------------------------
É o teste local da receita que coleta cerca de 1.100 linhas por rodada em produção
(desde 04/08/2026).

O HTML da rota atual, servido ao user-agent EnxameBot, está versionado desde 25/07
em `02_Dados/raw/experimento_cracha/`: as vitrines `toys` e `sports`, 50 produtos
cada. Copiá-lo para `tests/fixtures/` duplicaria 660 KB e criaria uma segunda cópia
do mesmo dado. Este teste lê o artefato no lugar onde ele está, no mesmo padrão dos
testes de `03_Analise/`.

Os números aqui são exatos, e podem ser: o HTML é imutável e versionado. Se algum número
mudar, foi a receita que mudou, que é justamente o que se quer monitorar.

O reparo de 23/07 reproduzido a partir dos artefatos
----------------------------------------------------
As receitas versionadas anteriores a 25/07 não têm `reparo_historico` (o campo foi
criado depois delas). A sequência do reparo, porém, está gravada nos próprios
seletores, e o veredito da proteção contra sobreajuste se reproduz aplicando as três
receitas ao HTML versionado, que é o que os testes abaixo fazem. Com isso o reparo
real de 23/07 passa a ser reproduzível por script, a partir de entradas versionadas.

Os números não são os mesmos da prova de 29/07 (`toys 0,996 para 0,0`, `sports 0,972
para 0,0`), porque aquela mediu as `paginas_validacao` declaradas na receita
(`electronics` e `kitchen`), buscadas ao vivo naquele dia. Aqui são `toys` e
`sports`, congeladas em 25/07. Páginas diferentes, datas diferentes, mesmo padrão; os
dois conjuntos de números não devem ser citados um no lugar do outro.
"""

import json
import re
from pathlib import Path

import pytest

from app import coletor
from app.agentes import analista_estrutura as ae

RECEITAS = Path(__file__).resolve().parent.parent / "receitas" / "www.amazon.com.br"
HTMLS = (
    Path(__file__).resolve().parent.parent.parent
    / "02_Dados" / "raw" / "experimento_cracha"
)
PAGINAS = {
    "toys": "20260725T032517Z_amazon_toys_EnxameBot.html",
    "sports": "20260725T032517Z_amazon_sports_EnxameBot.html",
}
CAMPOS = [{"nome": c} for c in ("titulo", "preco", "link", "rank", "avaliacao")]


def _html(vitrine: str) -> str:
    caminho = HTMLS / PAGINAS[vitrine]
    if not caminho.exists():  # pragma: no cover
        pytest.skip(f"HTML versionado ausente: {caminho}")
    return caminho.read_text(encoding="utf-8", errors="replace")


def _receita(arquivo: str) -> dict:
    return json.loads((RECEITAS / arquivo).read_text(encoding="utf-8"))


def _taxa_titulo(receita: dict, vitrine: str) -> float:
    linhas = ae.aplicar_receita(_html(vitrine), receita)
    return ae.validar_receita(linhas, [{"nome": "titulo"}])["campos"]["titulo"]["taxa"]


# ---------------------------------------------------------------------------
# A rota atual com teste local
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("vitrine", sorted(PAGINAS))
def test_receita_de_producao_extrai_as_50_posicoes(vitrine):
    """A vitrine de departamento serve 50 produtos com rank contínuo #1..#50."""
    receita = coletor.carregar_receita_mais_recente("www.amazon.com.br")
    validacao = ae.validar_receita(ae.aplicar_receita(_html(vitrine), receita), CAMPOS)
    assert validacao["itens_encontrados"] == 50
    assert ae.aprovada(validacao, receita) is True


@pytest.mark.parametrize("vitrine", sorted(PAGINAS))
def test_o_titulo_vem_em_100_por_cento_dos_itens(vitrine):
    """A regressão mais importante: é o campo que quebrou em produção.

    Em 22/07 o seletor do `titulo` fixava `line-clamp-3` e a vitrine Games e
    Consoles renderiza `line-clamp-1`, o que deu 18% de preenchimento, com a média
    dos 5 campos em 0,82. A régua da época aprovava, e o defeito persistiu por seis
    dias. Se este número sair de 1,0, o conserto de 23/07 regrediu.
    """
    receita = coletor.carregar_receita_mais_recente("www.amazon.com.br")
    assert _taxa_titulo(receita, vitrine) == 1.0


def test_a_receita_em_producao_nao_fixa_o_numero_de_LINHAS_do_titulo():
    """Fixa a propriedade que torna a receita robusta: ela é agnóstica ao clamp.

    O seletor agnóstico contém `line-clamp` (`[class*="p13n-sc-css-line-clamp"]`,
    casamento por prefixo, que pega `-1`, `-2` e `-3` igualmente). O que ele não faz
    é fixar o número, que foi a causa raiz de 22/07 e o que a candidata recusada
    (`._cDEzb_p13n-sc-css-line-clamp-1_1Fn1y`) fazia. Por isso o invariante testado é
    a ausência do dígito, não da palavra.
    """
    receita = coletor.carregar_receita_mais_recente("www.amazon.com.br")
    assert receita["seletor_item"] == ".zg-no-numbers"
    assert not re.search(r"line-clamp-\d", receita["campos"]["titulo"]["seletor"])
    assert "class*=" in receita["campos"]["titulo"]["seletor"]


# ---------------------------------------------------------------------------
# O reparo de 23/07, reproduzido a partir dos artefatos
# ---------------------------------------------------------------------------


def test_a_candidata_sobreajustada_de_23_07_destruiria_as_paginas_de_referencia():
    """A proteção contra sobreajuste acertou ao recusar a candidata, e isso é verificável.

    A candidata `receita_20260723_030834.json` fixa `line-clamp-1`: ela conserta a
    vitrine que falhou e zera as outras, porque a receita vale para o domínio.
    Medido contra o HTML versionado: `toys` cai a 0,06 e `sports` a 0,00.
    """
    sobreajustada = _receita("receita_20260723_030834.json")
    assert "line-clamp-1" in sobreajustada["campos"]["titulo"]["seletor"]
    assert _taxa_titulo(sobreajustada, "toys") == pytest.approx(0.06)
    assert _taxa_titulo(sobreajustada, "sports") == pytest.approx(0.0)


def test_a_agnostica_melhora_as_duas_referencias_e_por_isso_foi_aceita():
    """O contraste que completa o argumento: 0,92/0,86 no pai, 1,00/1,00 na aceita.

    É a sequência inteira do reparo de 23/07, obtida só de arquivos do repositório:
    pai (clamp-3), candidata sobreajustada (clamp-1, recusada), agnóstica (aceita).
    """
    pai = _receita("receita_20260716_013618.json")
    agnostica = _receita("receita_20260723_032219.json")

    assert _taxa_titulo(pai, "toys") == pytest.approx(0.92)
    assert _taxa_titulo(pai, "sports") == pytest.approx(0.86)
    assert _taxa_titulo(agnostica, "toys") == 1.0
    assert _taxa_titulo(agnostica, "sports") == 1.0

    # O que a proteção checa: a aceita não pode regredir em nenhuma referência.
    for vitrine in PAGINAS:
        assert _taxa_titulo(agnostica, vitrine) > _taxa_titulo(pai, vitrine)
