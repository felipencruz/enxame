"""Testes do coletor agendado, sem rede e sem LLM."""

import pytest

from app import bloqueio, coletor
from app.agentes import analista_estrutura, conformidade

HTML = """
<ul><li class="p"><h2 class="n">Produto A</h2><span class="v">R$ 10</span></li>
    <li class="p"><h2 class="n">Produto B</h2><span class="v">R$ 20</span></li></ul>
"""

RECEITA = {
    "seletor_item": "li.p",
    "campos": {"titulo": {"seletor": "h2.n", "origem": "texto"},
               "preco": {"seletor": "span.v", "origem": "texto"}},
    "_meta": {"dominio": "exemplo.com.br"},
}


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    conformidade.limpar_cache()
    # Agente 1 sempre libera
    monkeypatch.setattr(
        coletor.conformidade, "verificar",
        lambda url, ua: conformidade.Veredito(True, "ok", "r", crawl_delay=None),
    )
    # HTML fixo, sem rede
    # A assinatura do dublê acompanha a real: desde 04/08 o coletor passa o
    # `piso_bytes` do domínio (a régua de volume). Um dublê com assinatura antiga
    # falharia com TypeError em vez de exercitar o código.
    monkeypatch.setattr(coletor.coleta_http, "buscar_html", lambda url, ua, piso_bytes=None: HTML)
    yield


def test_coleta_usa_receita_salva_sem_llm(monkeypatch):
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: dict(RECEITA))
    # Se chamar o LLM, o teste falha de propósito:
    monkeypatch.setattr(
        analista_estrutura, "_chamar_llm",
        lambda m, **kw: (_ for _ in ()).throw(AssertionError("não deveria chamar o LLM")),
    )
    r = coletor.coletar("https://exemplo.com.br/lista", None, "http", "EnxameBot")
    assert r["llm_usado"] is False
    assert r["validacao"]["itens_encontrados"] == 2
    assert r["linhas"][0]["titulo"] == "Produto A"


def test_sem_receita_propoe_com_llm(monkeypatch):
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: None)
    monkeypatch.setattr(analista_estrutura, "_chamar_llm", lambda m, **kw: dict(RECEITA))
    monkeypatch.setattr(analista_estrutura, "salvar_receita", lambda rec, val=None, reparo=None, custo=None: "caminho/fake.json")
    r = coletor.coletar("https://exemplo.com.br/lista",
                        [{"nome": "titulo"}, {"nome": "preco"}], "http", "EnxameBot")
    assert r["llm_usado"] is True
    assert r["validacao"]["itens_encontrados"] == 2


def test_receita_quebrada_aciona_reparo(monkeypatch):
    receita_ruim = {"seletor_item": "div.naoexiste", "campos": RECEITA["campos"],
                    "_meta": {"dominio": "exemplo.com.br"}}
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: receita_ruim)
    monkeypatch.setattr(analista_estrutura, "_chamar_llm", lambda m, **kw: dict(RECEITA))
    monkeypatch.setattr(analista_estrutura, "salvar_receita", lambda rec, val=None, reparo=None, custo=None: "caminho/fake.json")
    r = coletor.coletar("https://exemplo.com.br/lista",
                        [{"nome": "titulo"}, {"nome": "preco"}], "http", "EnxameBot")
    assert r["reparado"] is True
    assert r["llm_usado"] is True
    assert r["validacao"]["itens_encontrados"] == 2


def test_primeira_receita_reprovada_falha_alto_e_nao_devolve_linhas(monkeypatch):
    """A régua vale também para a primeira receita, não só para o reparo.

    O caminho "sem receita salva" tem de consultar `aprovada` antes de devolver as
    linhas, assim como o caminho do reparo, que falha explicitamente para não poluir
    a Bronze, que é imutável. Sem isso, uma proposta alucinada chegaria à Bronze.

    O caso é real e está no repositório: `.item-class` foi o seletor que o LLM
    inventou ao receber a página anti-bot do ML em 13/07, com 0 itens.
    """
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: None)
    alucinada = {"seletor_item": ".item-class",
                 "campos": {"titulo": {"seletor": ".nada", "origem": "texto"}},
                 "_meta": {"dominio": "exemplo.com.br"}}
    monkeypatch.setattr(analista_estrutura, "_chamar_llm", lambda m, **kw: dict(alucinada))
    salvas = []
    monkeypatch.setattr(
        analista_estrutura, "salvar_receita",
        lambda rec, val=None, reparo=None, custo=None: salvas.append((rec, val)) or "/tmp/x.json",
    )

    with pytest.raises(RuntimeError, match="não passa na régua"):
        coletor.coletar("https://exemplo.com.br/lista", [{"nome": "titulo"}], "http", "EnxameBot")

    # Mas ela é salva como evidência: o erro do LLM é material de apêndice, e o
    # `_meta.aprovada: false` impede que o carregador a use depois.
    assert len(salvas) == 1
    assert salvas[0][1]["itens_encontrados"] == 0


def test_primeira_receita_boa_passa_e_declara_o_veredito(monkeypatch):
    """O contraste: proposta boa entra, e a resposta informa que ela passou."""
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: None)
    monkeypatch.setattr(analista_estrutura, "_chamar_llm", lambda m, **kw: dict(RECEITA))
    monkeypatch.setattr(
        analista_estrutura, "salvar_receita",
        lambda rec, val=None, reparo=None, custo=None: "/tmp/x.json",
    )
    r = coletor.coletar("https://exemplo.com.br/lista",
                        [{"nome": "titulo"}, {"nome": "preco"}], "http", "EnxameBot")
    assert r["aprovada"] is True
    assert r["validacao"]["itens_encontrados"] == 2


def test_sem_receita_e_sem_campos_erro(monkeypatch):
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: None)
    with pytest.raises(ValueError):
        coletor.coletar("https://exemplo.com.br/lista", None, "http", "EnxameBot")


def test_bloqueio_da_fonte_aborta_sem_chamar_o_llm(monkeypatch):
    """Risco de custo: fonte bloqueada rende 0 itens, mas a receita está intacta.
    O coletor tem de abortar, não reparar (senão gasta LLM sem necessidade)."""
    def _bloqueada(url, ua, piso_bytes=None):
        raise bloqueio.PaginaBloqueada(url, "HTTP 503")

    monkeypatch.setattr(coletor.coleta_http, "buscar_html", _bloqueada)
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: dict(RECEITA))
    monkeypatch.setattr(
        analista_estrutura, "_chamar_llm",
        lambda m, **kw: (_ for _ in ()).throw(AssertionError("bloqueio não pode acionar o LLM")),
    )
    with pytest.raises(bloqueio.PaginaBloqueada):
        coletor.coletar("https://www.amazon.com.br/gp/bestsellers/",
                        [{"nome": "titulo"}], "http", "EnxameBot")


# --- O gatilho do reparo é a régua, não a contagem de itens (15/07/2026) ------
#
# Se só zero itens (`if not linhas`) acionasse o Agente 4, uma receita que casa os
# itens mas lê quase nenhum campo passaria, e a coleta gravaria dados incompletos a
# cada 6h com `llm_usado: false`.

RECEITA_SO_UM_CAMPO = {
    "seletor_item": "li.p",
    "campos": {
        "titulo": {"seletor": "h2.n", "origem": "texto"},
        "preco": {"seletor": ".seletor-errado", "origem": "texto"},
        "link": {"seletor": ".tambem-errado", "origem": "atributo", "atributo": "href"},
    },
    "_meta": {"dominio": "exemplo.com.br"},
}


def test_receita_que_acha_itens_mas_nao_extrai_aciona_o_agente_4(monkeypatch):
    """2 itens achados, 1 campo de 3 preenchido (média 0,33): a régua reprova e o
    Supervisor é chamado. Um gatilho `if not linhas` deixaria passar."""
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: dict(RECEITA_SO_UM_CAMPO))
    chamou = {"reparar": False}

    def _reparo_fake(html, receita, campos, url, **kw):
        chamou["reparar"] = True
        boa = dict(RECEITA)
        val = analista_estrutura.validar_receita(
            analista_estrutura.aplicar_receita(html, boa), campos
        )
        return {"receita": boa, "validacao": val, "pontuacao": 1.0, "tentativas": 1, "historico": []}

    monkeypatch.setattr(coletor.supervisor, "reparar", _reparo_fake)
    monkeypatch.setattr(
        coletor.analista_estrutura, "salvar_receita",
        lambda r, v=None, reparo=None, custo=None: "/tmp/x.json",
    )

    r = coletor.coletar("https://exemplo.com.br/lista", None, "http", "EnxameBot")
    assert chamou["reparar"] is True
    assert r["reparado"] is True
    assert r["linhas"][0]["titulo"] == "Produto A"


def test_reparo_que_nao_passa_na_regua_falha_alto_e_nao_grava(monkeypatch):
    """Erro visível no n8n é melhor que Bronze poluída: se o Agente 4 não consegue
    uma receita aprovável, nada é gravado e nada é salvo."""
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: dict(RECEITA_SO_UM_CAMPO))
    salvou = {"n": 0}

    def _reparo_ruim(html, receita, campos, url, **kw):
        val = analista_estrutura.validar_receita(
            analista_estrutura.aplicar_receita(html, receita), campos
        )
        return {"receita": receita, "validacao": val, "pontuacao": 0.33, "tentativas": 3, "historico": []}

    def _conta_salvar(r, v=None, reparo=None, custo=None):
        salvou["n"] += 1
        return "/tmp/x.json"

    monkeypatch.setattr(coletor.supervisor, "reparar", _reparo_ruim)
    monkeypatch.setattr(coletor.analista_estrutura, "salvar_receita", _conta_salvar)

    with pytest.raises(RuntimeError, match="não passa na régua"):
        coletor.coletar("https://exemplo.com.br/lista", None, "http", "EnxameBot")
    assert salvou["n"] == 0


def test_receita_boa_nao_aciona_o_agente_4(monkeypatch):
    """O caso oposto: a régua não pode chamar o LLM sem necessidade numa receita
    que está funcionando."""
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: dict(RECEITA))
    monkeypatch.setattr(
        coletor.supervisor, "reparar",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("não deveria reparar receita boa")),
    )
    r = coletor.coletar("https://exemplo.com.br/lista", None, "http", "EnxameBot")
    assert r["llm_usado"] is False
    assert r["reparado"] is False


# --- A descrição dos campos sobrevive até o reparo (15/07/2026) ---------------
#
# Medido: o Analista propõe a receita do layout de departamento da Amazon com
# pontuação 0,984 quando recebe a descrição de cada campo, e 0,167 quando recebe
# só os nomes. A coleta agendada só conhece a receita salva; sem guardar o pedido
# original junto dela, o reparo do Agente 4 seria feito sem as descrições.

RECEITA_COM_PEDIDO = {
    "seletor_item": "li.p",
    "campos": {"titulo": {"seletor": "h2.n", "origem": "texto"},
               "preco": {"seletor": "span.v", "origem": "texto"}},
    "_meta": {
        "dominio": "exemplo.com.br",
        "campos_pedidos": [
            {"nome": "titulo", "descricao": "nome do produto"},
            {"nome": "preco", "descricao": "preco em reais"},
        ],
    },
}


def test_campos_da_receita_anexa_a_descricao_guardada():
    campos = coletor._campos_da_receita(RECEITA_COM_PEDIDO)
    assert {c["nome"]: c["descricao"] for c in campos} == {
        "titulo": "nome do produto", "preco": "preco em reais",
    }


def test_receita_antiga_sem_o_pedido_continua_funcionando():
    """Compatibilidade: receita anterior a 15/07 não tem `campos_pedidos`."""
    campos = coletor._campos_da_receita(RECEITA)
    assert [c["nome"] for c in campos] == ["titulo", "preco"]
    assert all(c["descricao"] == "" for c in campos)


def test_os_nomes_saem_da_receita_nao_do_pedido():
    """Quem define o que a receita produz é a própria receita. Se o pedido guardado
    divergir (campo a mais, campo a menos), o conjunto medido não muda; caso
    contrário, a régua passaria a medir outra coisa e o veredito de aprovação
    mudaria sem que a receita mudasse."""
    receita = {
        "seletor_item": "li.p",
        "campos": {"titulo": {"seletor": "h2.n", "origem": "texto"}},
        "_meta": {"dominio": "x.com", "campos_pedidos": [
            {"nome": "titulo", "descricao": "nome"},
            {"nome": "campo_fantasma", "descricao": "nao existe na receita"},
        ]},
    }
    assert [c["nome"] for c in coletor._campos_da_receita(receita)] == ["titulo"]


def test_a_descricao_chega_ao_agente_4_no_reparo(monkeypatch):
    """O objetivo do mecanismo: no reparo, o Supervisor recebe os campos com descrição."""
    quebrada = {
        "seletor_item": "li.p",
        "campos": {"titulo": {"seletor": ".nao-existe", "origem": "texto"},
                   "preco": {"seletor": ".tambem-nao", "origem": "texto"}},
        "_meta": {"dominio": "exemplo.com.br", "campos_pedidos": [
            {"nome": "titulo", "descricao": "nome do produto"},
            {"nome": "preco", "descricao": "preco em reais"},
        ]},
    }
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: dict(quebrada))
    recebidos = {}

    def _espiao(html, receita, campos, url, **kw):
        recebidos["campos"] = campos
        boa = dict(RECEITA)
        val = analista_estrutura.validar_receita(analista_estrutura.aplicar_receita(html, boa), campos)
        return {"receita": boa, "validacao": val, "pontuacao": 1.0, "tentativas": 1, "historico": []}

    monkeypatch.setattr(coletor.supervisor, "reparar", _espiao)
    monkeypatch.setattr(
        coletor.analista_estrutura, "salvar_receita",
        lambda r, v=None, reparo=None, custo=None: "/tmp/x.json",
    )
    coletor.coletar("https://exemplo.com.br/lista", None, "http", "EnxameBot")

    assert {c["nome"]: c["descricao"] for c in recebidos["campos"]} == {
        "titulo": "nome do produto", "preco": "preco em reais",
    }


# --- Agente 3 ponta a ponta: o tipo chega, e a régua reprova o vizinho errado ---

HTML_NOTA = """
<ul>
  <li class="p"><h2 class="n">Air Fryer</h2>
      <span class="nota">4,8</span><span class="qtd">19.614</span></li>
  <li class="p"><h2 class="n">Uno</h2>
      <span class="nota">4,9</span><span class="qtd">36.629</span></li>
</ul>
"""

# O erro típico: o seletor pegou a contagem de avaliações em vez da nota.
# Preenche 100% dos itens, é número, parece dado bom, e está errado.
RECEITA_VIZINHO_ERRADO = {
    "seletor_item": "li.p",
    "campos": {"titulo": {"seletor": "h2.n", "origem": "texto"},
               "nota": {"seletor": "span.qtd", "origem": "texto"}},
    "_meta": {"dominio": "exemplo.com.br", "campos_pedidos": [
        {"nome": "titulo", "descricao": "nome do produto", "tipo": "texto"},
        {"nome": "nota", "descricao": "nota de 0 a 5", "tipo": "nota"},
    ]},
}


def test_o_tipo_do_pedido_chega_ao_coletor():
    campos = coletor._campos_da_receita(RECEITA_VIZINHO_ERRADO)
    assert {c["nome"]: c["tipo"] for c in campos} == {"titulo": "texto", "nota": "nota"}


def test_seletor_no_vizinho_errado_e_reprovado_e_aciona_o_agente_4(monkeypatch):
    """Ponta a ponta: 2 itens, `nota` 100% preenchida com 19.614, fora da faixa 0 a 5.
    A régua reprova e o Supervisor é chamado. Sem a validação de tipo, isto passaria
    (100% de preenchimento) e a coleta gravaria a contagem no lugar da nota."""
    monkeypatch.setattr(coletor.coleta_http, "buscar_html", lambda url, ua, piso_bytes=None: HTML_NOTA)
    monkeypatch.setattr(coletor, "carregar_receita_mais_recente", lambda dom: dict(RECEITA_VIZINHO_ERRADO))
    visto = {}

    def _reparo(html, receita, campos, url, **kw):
        visto["problemas"] = coletor.supervisor.diagnosticar(
            receita, analista_estrutura.validar_receita(
                analista_estrutura.aplicar_receita(html, receita), campos))
        boa = dict(RECEITA_VIZINHO_ERRADO)
        boa["campos"] = {**boa["campos"], "nota": {"seletor": "span.nota", "origem": "texto"}}
        val = analista_estrutura.validar_receita(analista_estrutura.aplicar_receita(html, boa), campos)
        return {"receita": boa, "validacao": val, "pontuacao": 1.0, "tentativas": 1, "historico": []}

    monkeypatch.setattr(coletor.supervisor, "reparar", _reparo)
    monkeypatch.setattr(
        coletor.analista_estrutura, "salvar_receita",
        lambda r, v=None, reparo=None, custo=None: "/tmp/x.json",
    )

    r = coletor.coletar("https://exemplo.com.br/lista", None, "http", "EnxameBot")

    assert r["reparado"] is True
    assert r["linhas"][0]["nota"] == "4,8"  # o reparo pegou a nota, não a contagem
    # E o diagnóstico entregue ao LLM distingue "achou a coisa errada" de "não achou":
    diag = " ".join(visto["problemas"])
    assert "PREENCHE 100%" in diag and "válido" in diag
