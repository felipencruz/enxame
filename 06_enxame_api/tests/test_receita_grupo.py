"""Testes do formato de receita com grupo (vitrine ou carrossel como categoria).

Motivação real (Amazon): o rank reinicia a cada carrossel (#1 de Cozinha, #1 de
Moda), então a categoria precisa vir junto de cada produto, e ela fica acima do
item, fora do alcance de um seletor relativo ao item.
"""

from app.agentes import analista_estrutura as ae

HTML = """
<div class="shoveler">
  <h2 class="head">Mais Vendidos em Cozinha</h2>
  <li class="card"><div data-asin="A1"><span class="rank">#1</span>
    <span><div class="nome">Sanduicheira</div></span><span class="preco">R$ 99</span></div></li>
  <li class="card"><div data-asin="A2"><span class="rank">#2</span>
    <span><div class="nome">Filtro</div></span></div></li>
</div>
<div class="shoveler">
  <h2 class="head">Mais Vendidos em Moda</h2>
  <li class="card"><div data-asin="B1"><span class="rank">#1</span>
    <span><div class="nome">Tenis</div></span><span class="preco">R$ 199</span></div></li>
</div>
"""

RECEITA_GRUPO = {
    "seletor_grupo": "div.shoveler",
    "campos_grupo": {"categoria": {"seletor": "h2.head", "origem": "texto"}},
    "seletor_item": "li.card > div[data-asin]",
    "campos": {
        "titulo": {"seletor": "div.nome", "origem": "texto"},
        "rank": {"seletor": "span.rank", "origem": "texto"},
        "preco": {"seletor": "span.preco", "origem": "texto"},
        "asin": {"seletor": "", "origem": "texto"},
    },
}


def test_categoria_do_grupo_se_replica_em_cada_item():
    receita = {**RECEITA_GRUPO, "campos": {k: v for k, v in RECEITA_GRUPO["campos"].items() if k != "asin"}}
    linhas = ae.aplicar_receita(HTML, receita)
    assert len(linhas) == 3
    assert [l["categoria"] for l in linhas] == [
        "Mais Vendidos em Cozinha",
        "Mais Vendidos em Cozinha",
        "Mais Vendidos em Moda",
    ]


def test_rank_so_faz_sentido_com_a_categoria_junto():
    """Os dois '#1' da página são de categorias diferentes; sem grupo, virariam duplicata."""
    receita = {**RECEITA_GRUPO, "campos": {k: v for k, v in RECEITA_GRUPO["campos"].items() if k != "asin"}}
    linhas = ae.aplicar_receita(HTML, receita)
    primeiros = [(l["categoria"], l["rank"]) for l in linhas if l["rank"] == "#1"]
    assert primeiros == [("Mais Vendidos em Cozinha", "#1"), ("Mais Vendidos em Moda", "#1")]


def test_item_sem_o_campo_fica_nulo_e_nao_quebra():
    receita = {**RECEITA_GRUPO, "campos": {k: v for k, v in RECEITA_GRUPO["campos"].items() if k != "asin"}}
    linhas = ae.aplicar_receita(HTML, receita)
    assert linhas[1]["preco"] is None
    assert linhas[1]["titulo"] == "Filtro"


def test_receita_sem_grupo_continua_igual():
    """Compatibilidade: a receita do ML (em produção) não tem grupo."""
    receita = {
        "seletor_item": "li.card > div[data-asin]",
        "campos": {"titulo": {"seletor": "div.nome", "origem": "texto"}},
    }
    linhas = ae.aplicar_receita(HTML, receita)
    assert len(linhas) == 3
    assert "categoria" not in linhas[0]
    assert linhas[0]["titulo"] == "Sanduicheira"


def test_seletor_de_grupo_que_nao_casa_devolve_vazio():
    """Se a vitrine sumir do HTML, a receita rende 0 linhas, o que aciona o reparo."""
    receita = {**RECEITA_GRUPO, "seletor_grupo": "div.naoexiste"}
    assert ae.aplicar_receita(HTML, receita) == []
