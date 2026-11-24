"""A regressão campo a campo da receita do Mercado Livre.

Por que este arquivo existe
---------------------------
A prova controlada de 29/07 registrou três reparos do ML com nota 0,9352, e o
`LEIA-ME.md` daquela pasta os descreveu como "receita MELHOR que a de produção
(0,7685)". Medido em 05/08 contra o mesmo HTML versionado que a prova usou, a
comparação não era entre produção e candidata:

  - 0,9352 é a nota da receita de produção naquela página;
  - 0,7685 é a nota de uma receita com um campo zerado. A receita mede 6 campos,
    então cada campo perdido custa 0,1667 da média, e 0,9352 - 0,1667 = 0,7685. O
    valor de "antes do reparo" nos casos `titulo_sumido` e `preco_sumido` é a nota
    da receita sabotada, não da que está no ar (ver `prova_auto_reparo.py`, campo
    `antes_do_reparo.pontuacao`).

O que os três reparos fizeram foi reencontrar um equivalente funcional exato da
receita original depois de ela ter sido quebrada de propósito, cada um por um
caminho diferente. Isso é um resultado favorável ao auto-reparo, e não um motivo
para trocar a receita.

A limitação que permanece
-------------------------
O reparo do caso `grupo_no_titulo` devolveu uma receita funcionalmente inferior: ela
perde `categoria` em 100% dos itens (o container do carrossel não envolve o `h2` do
título da vitrine) e mesmo assim passa na régua, porque `categoria` não é campo
essencial e a média dos outros cinco a sustenta. Em produção, a proteção contra
sobreajuste não pegaria isto: no Mercado Livre ela não roda, porque o `robots.txt`
não permite uma segunda rota de referência. O teste abaixo fixa esse caso: se ele
deixar de perder a categoria, é porque a régua mudou.

Os números são exatos porque as entradas são imutáveis e versionadas: o HTML de
29/07 (`sonda_reabertura_ml_20260729/`), a receita de produção e as `receita_reparada`
gravadas no artefato da prova. Se um número mudar, mudou a régua ou a receita, que é
o que se quer monitorar. A parte ao vivo desta medição não cabe aqui (a página muda
a cada rodada); ela está na sonda `sondas/sonda_regressao_receita_ml.py`.
"""

import json
from pathlib import Path

import pytest

from app import coletor
from app.agentes import analista_estrutura as ae
from app.agentes import supervisor

RAIZ = Path(__file__).resolve().parent.parent.parent
HTML = (
    RAIZ / "02_Dados" / "raw" / "sonda_reabertura_ml_20260729"
    / "20260729T020816Z_ml_mais-vendidos_EnxameBot.html"
)
PROVA = (
    RAIZ / "02_Dados" / "raw" / "prova_auto_reparo_20260729"
    / "prova_auto_reparo_20260729T023215Z.json"
)
PRODUCAO = (
    Path(__file__).resolve().parent.parent / "receitas" / "www.mercadolivre.com.br"
    / "receita_20260715_045658.json"
)
CAMPOS = ("categoria", "titulo", "preco", "preco_antigo", "desconto", "link")
# caso da prova -> rótulo desta regressão
REPAROS = {
    "item_inexistente": "reparo_item",
    "titulo_sumido": "reparo_titulo",
    "grupo_no_titulo": "reparo_grupo",
}


def _texto(caminho: Path) -> str:
    if not caminho.exists():  # pragma: no cover
        pytest.skip(f"artefato versionado ausente: {caminho}")
    return caminho.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def html() -> str:
    return _texto(HTML)


@pytest.fixture(scope="module")
def producao() -> dict:
    return json.loads(_texto(PRODUCAO))


@pytest.fixture(scope="module")
def reparadas(producao) -> dict:
    """As receitas que o Agente 4 devolveu, lidas do artefato, e não reescritas à mão.

    O `_meta` da produção é anexado porque `_campos_da_receita` lê dali os tipos
    declarados: sem ele a régua mediria as variantes com um critério diferente do
    da produção, e a comparação deixaria de ser campo a campo.
    """
    casos = {
        c["caso"]: c
        for c in json.loads(_texto(PROVA))["dominios"]["www.mercadolivre.com.br"]["casos"]
    }
    saida = {}
    for caso, rotulo in REPAROS.items():
        receita = json.loads(json.dumps(casos[caso]["receita_reparada"]))
        receita["_meta"] = producao["_meta"]
        saida[rotulo] = receita
    return saida


def _medir(html: str, receita: dict):
    linhas = ae.aplicar_receita(html, receita)
    validacao = ae.validar_receita(linhas, coletor._campos_da_receita(receita))
    return linhas, validacao


def _por_link(linhas: list[dict]) -> dict:
    return {(l.get("link") or "").split("#")[0]: l for l in linhas}


# --- a origem dos números 0,9352 e 0,7685 ---------------------------------------


def test_producao_pontua_9352_no_html_da_prova(html, producao):
    """0,9352 é a nota da receita de produção, e não de uma candidata."""
    _, validacao = _medir(html, producao)
    assert validacao["itens_encontrados"] == 162
    assert supervisor.pontuar(validacao) == 0.9352
    assert ae.aprovada(validacao, producao) is True


def test_7685_e_a_producao_menos_um_campo(html, producao):
    """0,7685 não é a nota de nenhuma receita em produção: é a produção com um campo
    zerado. Fixar a aritmética impede que o número seja lido como a nota da receita
    atual."""
    _, validacao = _medir(html, producao)
    nota = supervisor.pontuar(validacao)
    assert round(nota - 1 / len(CAMPOS), 4) == 0.7685


# --- a regressão propriamente dita ----------------------------------------------


@pytest.mark.parametrize("rotulo", ["reparo_item", "reparo_titulo"])
def test_reparo_devolve_equivalente_exato_da_producao(html, producao, reparadas, rotulo):
    """Mesma nota, mesmos itens, mesmos valores, campo a campo, item a item.

    É a regressão exigida antes de trocar uma receita; aqui ela mostra que não há o
    que trocar.
    """
    linhas_prod, val_prod = _medir(html, producao)
    linhas_var, val_var = _medir(html, reparadas[rotulo])

    assert supervisor.pontuar(val_var) == supervisor.pontuar(val_prod) == 0.9352
    assert val_var["itens_encontrados"] == val_prod["itens_encontrados"] == 162

    base, atual = _por_link(linhas_prod), _por_link(linhas_var)
    assert set(base) == set(atual), "o conjunto de itens mudou"
    for link, linha in base.items():
        for campo in CAMPOS:
            assert (linha.get(campo) or None) == (atual[link].get(campo) or None), (
                f"{rotulo}: divergência em {campo} no item {link}"
            )


def test_reparo_do_grupo_perde_a_categoria_e_a_regua_aprova(html, producao, reparadas):
    """O caso restante, que é uma limitação e não um empate.

    A candidata do `grupo_no_titulo` extrai os mesmos 162 itens, mas com `categoria`
    vazia em todos, e a régua a aprova. No ML a proteção contra sobreajuste não roda
    (não há segunda rota permitida pelo robots.txt), então nada barraria esta troca.
    """
    linhas_prod, _ = _medir(html, producao)
    linhas_var, val_var = _medir(html, reparadas["reparo_grupo"])

    assert val_var["campos"]["categoria"]["taxa"] == 0.0
    assert supervisor.pontuar(val_var) == 0.7685
    assert ae.aprovada(val_var, reparadas["reparo_grupo"]) is True, (
        "se isto falhar, a régua passou a reprovar perda de campo não-essencial — "
        "boa notícia, mas o limite 7 precisa ser reescrito"
    )

    base, atual = _por_link(linhas_prod), _por_link(linhas_var)
    assert set(base) == set(atual)
    assert all(atual[k].get("categoria") is None for k in base)
    assert all(base[k].get("categoria") for k in base)


def test_a_candidata_do_leia_me_nunca_foi_proposta(html, producao, reparadas):
    """A candidata descrita no `LEIA-ME.md` da prova (`seletor_item` novo e `titulo`
    novo juntos) é a fusão de dois reparos de casos diferentes; nenhum agente propôs
    as duas mudanças na mesma receita. Ainda assim ela é medida, e o resultado é o
    mesmo empate."""
    for rotulo in ("reparo_item", "reparo_titulo"):
        divergentes = [
            campo
            for campo in ("seletor_item", "seletor_grupo")
            if reparadas[rotulo].get(campo) != producao.get(campo)
        ] + [
            campo
            for campo, regra in reparadas[rotulo]["campos"].items()
            if regra.get("seletor") != producao["campos"][campo].get("seletor")
        ]
        assert len(divergentes) == 1, f"{rotulo} deveria divergir em UM seletor só"

    fusao = json.loads(json.dumps(producao))
    fusao["seletor_item"] = reparadas["reparo_item"]["seletor_item"]
    fusao["campos"]["titulo"]["seletor"] = reparadas["reparo_titulo"]["campos"]["titulo"]["seletor"]

    linhas_prod, val_prod = _medir(html, producao)
    linhas_fus, val_fus = _medir(html, fusao)
    assert supervisor.pontuar(val_fus) == supervisor.pontuar(val_prod)
    base, atual = _por_link(linhas_prod), _por_link(linhas_fus)
    assert set(base) == set(atual)
    for link, linha in base.items():
        for campo in CAMPOS:
            assert (linha.get(campo) or None) == (atual[link].get(campo) or None)
