"""Agente 3: validação de tipo e faixa (15/07/2026).

Medir só preenchimento indica se o campo veio, não se o valor é válido. Um seletor
apontado para o elemento vizinho preenche 100% dos itens com o dado errado e passa.

O caso típico é o da `nota`: se o seletor pega o número de avaliações (19.614) em
vez da nota (4,8), o preenchimento marca 100%. É número e parece dado bom. Só a
faixa revela o erro: a nota fica entre 0 e 5.

Limitação declarada: isto valida tipo e faixa, não formato. O caso da Amazon
("4,8 de 5 estrelas19.614", com o número colado) começa com 4,8 e passa aqui; isso
está testado abaixo, para que a limitação fique explícita.
"""

import pytest

from app.agentes import analista_estrutura as ae

LINHAS_BOAS = [
    {"titulo": "Air Fryer 4L", "preco": "R$ 299,90", "nota": "4,8 de 5 estrelas, 19.614 classificações",
     "rank": "#1", "link": "/dp/B000J445XA", "desconto": "20% OFF"},
    {"titulo": "Uno Original", "preco": "R$ 17,80", "nota": "4,9 de 5 estrelas, 36.629 classificações",
     "rank": "#2", "link": "https://www.amazon.com.br/dp/B00CTH0A1Q", "desconto": "5% OFF"},
]
CAMPOS = [
    {"nome": "titulo", "tipo": "texto"}, {"nome": "preco", "tipo": "preco"},
    {"nome": "nota", "tipo": "nota"}, {"nome": "rank", "tipo": "rank"},
    {"nome": "link", "tipo": "url"}, {"nome": "desconto", "tipo": "percentual"},
]


def test_dado_bom_passa_em_tudo():
    v = ae.validar_receita(LINHAS_BOAS, CAMPOS)
    for nome, m in v["campos"].items():
        assert m["taxa"] == 1.0, nome
        assert m["taxa_valida"] == 1.0, nome
    assert ae.aprovada(v) is True


def test_o_caso_canonico_seletor_pegou_o_numero_de_avaliacoes():
    """100% preenchido, 0% válido: 19.614 é número, mas a nota fica entre 0 e 5.
    Uma régua só de preenchimento aprovaria isto."""
    linhas = [{"nota": "19.614"}, {"nota": "36.629"}]
    v = ae.validar_receita(linhas, [{"nome": "nota", "tipo": "nota"}])
    assert v["campos"]["nota"]["taxa"] == 1.0        # veio
    assert v["campos"]["nota"]["taxa_valida"] == 0.0  # e não é válido
    assert ae.aprovada(v) is False


def test_preco_tem_de_ser_positivo():
    v = ae.validar_receita([{"preco": "R$ 0,00"}, {"preco": "Frete grátis"}],
                           [{"nome": "preco", "tipo": "preco"}])
    assert v["campos"]["preco"]["taxa"] == 1.0
    assert v["campos"]["preco"]["taxa_valida"] == 0.0


def test_rank_tem_de_ser_hash_numero():
    v = ae.validar_receita([{"rank": "#1"}, {"rank": "Mais vendido"}, {"rank": "#0"}],
                           [{"nome": "rank", "tipo": "rank"}])
    assert v["campos"]["rank"]["taxa"] == 1.0
    assert round(v["campos"]["rank"]["taxa_valida"], 2) == 0.33


def test_campo_sem_tipo_declarado_e_medido_como_antes():
    """Compatibilidade: receita que não declara tipo é medida só por preenchimento."""
    v = ae.validar_receita([{"x": "qualquer coisa"}], [{"nome": "x"}])
    assert v["campos"]["x"]["taxa"] == 1.0
    assert v["campos"]["x"]["taxa_valida"] == 1.0
    assert v["campos"]["x"]["tipo"] is None


def test_o_que_a_validacao_de_tipo_NAO_pega():
    """Alcance da validação: o caso da Amazon (a nota certa com o número de avaliações
    colado) começa com 4,8 e passa na faixa. Detectar isto exigiria validação de
    formato, que muda a cada alteração no texto do site e ficou fora do escopo. Este
    teste documenta a limitação."""
    v = ae.validar_receita([{"nota": "4,8 de 5 estrelas19.614"}], [{"nome": "nota", "tipo": "nota"}])
    assert v["campos"]["nota"]["taxa_valida"] == 1.0   # passa, como esperado


def test_faixa_da_nota_nas_bordas():
    v = ae.validar_receita(
        [{"n": "0"}, {"n": "5"}, {"n": "5,1"}, {"n": "-1"}], [{"nome": "n", "tipo": "nota"}]
    )
    assert v["campos"]["n"]["taxa_valida"] == 0.5  # 0 e 5 entram; 5,1 e -1 não


def test_campo_tipado_que_enche_e_nunca_valida_reprova_sozinho():
    """A média não pode diluir defeito: com 2 campos, um perfeito e um 100% errado, a
    média daria exatamente 0,5 e passaria no limite. Campo tipado que preenche e nunca
    valida indica seletor no elemento errado, e isso reprova independentemente da média."""
    v = ae.validar_receita(
        [{"titulo": "Air Fryer", "nota": "19.614"}, {"titulo": "Uno", "nota": "36.629"}],
        [{"nome": "titulo", "tipo": "texto"}, {"nome": "nota", "tipo": "nota"}],
    )
    assert v["campos"]["titulo"]["taxa_valida"] == 1.0
    assert v["campos"]["nota"]["taxa_valida"] == 0.0
    # média = 0,5: passaria pela régua da média; a reprovação direta é que detecta
    assert ae.aprovada(v) is False


def test_campo_parcialmente_ausente_nao_e_reprovacao_dura():
    """O caso oposto: `preco_antigo` do ML vem em cerca de 75% dos itens (só os que têm
    desconto). Isso é característica da fonte, não defeito, e não pode reprovar
    receita saudável."""
    linhas = [{"preco_antigo": "R$ 10,00"}, {"preco_antigo": None}, {"preco_antigo": "R$ 20,00"},
              {"preco_antigo": "R$ 30,00"}]
    v = ae.validar_receita(linhas, [{"nome": "preco_antigo", "tipo": "preco"}])
    assert v["campos"]["preco_antigo"]["taxa_valida"] == 0.75
    assert ae.aprovada(v) is True


# --- A API recusa tipo desconhecido (16/07) -----------------------------------

def test_api_recusa_tipo_desconhecido():
    """Sem esta trava, um `"preço"` com cedilha desligaria a validação do Agente 3 sem
    aviso: VALIDADORES.get() devolve None, taxa_valida vira taxa, e o campo volta a ser
    medido só por presença. A validação no Pydantic impede essa falha silenciosa."""
    import pydantic
    from app.main import CampoDesejado

    with pytest.raises(pydantic.ValidationError, match="não existe"):
        CampoDesejado(nome="preco", tipo="preço")   # cedilha: erro comum de digitação

    with pytest.raises(pydantic.ValidationError):
        CampoDesejado(nome="x", tipo="inventado")


def test_api_aceita_os_tipos_conhecidos_e_o_ausente():
    from app.main import CampoDesejado

    for tipo in ae.VALIDADORES:
        assert CampoDesejado(nome="x", tipo=tipo).tipo == tipo
    assert CampoDesejado(nome="x").tipo is None   # sem tipo continua valendo
