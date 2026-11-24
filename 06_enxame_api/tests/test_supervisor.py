"""Testes do Agente 4 (Supervisor e Reparador), sem rede e sem LLM.

O princípio que estes testes fixam: quem mede e quem decide é o código.
O LLM só propõe seletores; uma receita nova só entra se pontuar mais alto.
"""

import pytest

from app.agentes import analista_estrutura as ae
from app.agentes import supervisor

HTML = """
<div class="vitrine"><h2 class="head">Cozinha</h2>
  <li class="card"><div class="nome">Sanduicheira</div><span class="v">R$ 99</span></li>
  <li class="card"><div class="nome">Filtro</div><span class="v">R$ 65</span></li>
</div>
"""

CAMPOS = [{"nome": "categoria"}, {"nome": "titulo"}, {"nome": "preco"}]

RECEITA_BOA = {
    "seletor_grupo": "div.vitrine",
    "campos_grupo": {"categoria": {"seletor": "h2.head", "origem": "texto"}},
    "seletor_item": "li.card",
    "campos": {"titulo": {"seletor": "div.nome", "origem": "texto"},
               "preco": {"seletor": "span.v", "origem": "texto"}},
}

# O erro real cometido pelo Agente 2 na Amazon: o grupo aponta para o título da
# vitrine em vez do contêiner, e os itens somem.
RECEITA_QUEBRADA = {**RECEITA_BOA, "seletor_grupo": "h2.head"}


def _validar(receita):
    return ae.validar_receita(ae.aplicar_receita(HTML, receita), CAMPOS)


def test_pontuar_receita_sem_itens_e_zero():
    assert supervisor.pontuar(_validar(RECEITA_QUEBRADA)) == 0.0


def test_pontuar_receita_boa_e_um():
    assert supervisor.pontuar(_validar(RECEITA_BOA)) == 1.0


def test_diagnostico_de_zero_itens_aponta_o_grupo():
    problemas = supervisor.diagnosticar(RECEITA_QUEBRADA, _validar(RECEITA_QUEBRADA))
    assert len(problemas) == 1
    assert "NENHUM item" in problemas[0]
    assert "CONTÊINER" in problemas[0]  # a dica que o LLM precisa para acertar


def test_diagnostico_aponta_campo_com_seletor_errado():
    receita = {**RECEITA_BOA, "campos": {**RECEITA_BOA["campos"],
                                         "preco": {"seletor": "span.naoexiste", "origem": "texto"}}}
    problemas = supervisor.diagnosticar(receita, _validar(receita))
    assert any("'preco'" in p and "span.naoexiste" in p for p in problemas)


def test_receita_boa_nao_tem_diagnostico():
    assert supervisor.diagnosticar(RECEITA_BOA, _validar(RECEITA_BOA)) == []


def test_reparo_aceita_proposta_melhor(monkeypatch):
    monkeypatch.setattr(ae, "_chamar_llm", lambda m, **kw: dict(RECEITA_BOA))
    r = supervisor.reparar(HTML, RECEITA_QUEBRADA, CAMPOS, "https://x.com/l", max_tentativas=2)
    assert r["pontuacao"] == 1.0
    assert r["receita"]["seletor_grupo"] == "div.vitrine"
    assert r["tentativas"] == 1  # acertou na primeira e parou


def test_reparo_recusa_proposta_pior_e_mantem_a_original(monkeypatch):
    """O LLM não se autoavalia: proposta que piora é descartada pelo código."""
    pior = {**RECEITA_BOA, "seletor_item": "li.inexistente"}
    monkeypatch.setattr(ae, "_chamar_llm", lambda m, **kw: dict(pior))
    r = supervisor.reparar(HTML, RECEITA_BOA, CAMPOS, "https://x.com/l", max_tentativas=2)
    assert r["receita"]["seletor_item"] == "li.card"  # manteve a boa
    assert r["pontuacao"] == 1.0


def test_reparo_nao_chama_llm_se_receita_ja_esta_boa(monkeypatch):
    monkeypatch.setattr(
        ae, "_chamar_llm",
        lambda m, **kw: (_ for _ in ()).throw(AssertionError("receita sã não deve custar LLM")),
    )
    r = supervisor.reparar(HTML, RECEITA_BOA, CAMPOS, "https://x.com/l")
    assert r["tentativas"] == 0
    assert r["pontuacao"] == 1.0


def test_reparo_desiste_apos_o_limite_de_tentativas(monkeypatch):
    chamadas = []

    def _llm_teimoso(m, **kw):
        chamadas.append(1)
        return {**RECEITA_BOA, "seletor_grupo": "h2.head"}  # insiste no erro

    monkeypatch.setattr(ae, "_chamar_llm", _llm_teimoso)
    r = supervisor.reparar(HTML, RECEITA_QUEBRADA, CAMPOS, "https://x.com/l", max_tentativas=2)
    assert len(chamadas) == 2  # respeitou o limite: não gasta LLM indefinidamente
    assert r["pontuacao"] == 0.0


def test_historico_registra_cada_tentativa(monkeypatch):
    """Trilha auditável para o apêndice da monografia."""
    monkeypatch.setattr(ae, "_chamar_llm", lambda m, **kw: dict(RECEITA_BOA))
    r = supervisor.reparar(HTML, RECEITA_QUEBRADA, CAMPOS, "https://x.com/l", max_tentativas=2)
    assert r["historico"][0]["pontuacao"] == 0.0
    assert r["historico"][1]["pontuacao"] == 1.0
    assert r["historico"][1]["aceita"] is True


def test_campo_ausente_confirmado_nao_e_defeito():
    """Fonte que omite um campo (Amazon e preço) não é receita quebrada: nenhum
    reparo o traria de volta, e insistir só gastaria LLM a cada rodada."""
    receita = {**RECEITA_BOA,
               "campos": {**RECEITA_BOA["campos"], "preco": None},
               "_meta": {"campos_ausentes": {"preco": "a fonte não publica"}}}
    val = _validar(receita)
    assert val["campos"]["preco"]["taxa"] == 0.0
    assert supervisor.diagnosticar(receita, val) == []


def test_campo_null_sem_registro_tambem_e_decisao_deliberada():
    """Prompt do Analista: campo inexistente na página vira null de propósito."""
    receita = {**RECEITA_BOA, "campos": {**RECEITA_BOA["campos"], "preco": None}}
    assert supervisor.diagnosticar(receita, _validar(receita)) == []


def test_campo_esquecido_continua_sendo_defeito():
    """O contraste: campo que a receita simplesmente não mapeou continua sendo defeito."""
    receita = {**RECEITA_BOA, "campos": {k: v for k, v in RECEITA_BOA["campos"].items() if k != "preco"}}
    problemas = supervisor.diagnosticar(receita, _validar(receita))
    assert any("não foi mapeado" in p for p in problemas)


# ---------------------------------------------------------------------------
# Validação multi-página (desde 23/07): a proteção contra sobreajuste
# ---------------------------------------------------------------------------

# Duas páginas do mesmo domínio com a mesma estrutura, mas classes de título
# diferentes, como no caso real da Amazon: a vitrine que falhou usa `clamp-1` e as
# outras usam `clamp-3`. A receita é uma por domínio, então atender só uma página
# quebra as outras.
PAGINA_QUE_FALHOU = """
<ul><li class="card"><a class="link"><div class="clamp1">Controle DualSense</div></a></li>
    <li class="card"><a class="link"><div class="clamp1">Nintendo Switch 2</div></a></li></ul>
"""
PAGINA_DE_REFERENCIA = """
<ul><li class="card"><a class="link"><div class="clamp3">Mixer Turbo Elgin 200W</div></a></li>
    <li class="card"><a class="link"><div class="clamp3">Sanduicheira Cadence 127V</div></a></li></ul>
"""

CAMPOS_T = [{"nome": "titulo"}]
RECEITA_CLAMP3 = {
    "seletor_item": "li.card",
    "campos": {"titulo": {"seletor": ".clamp3", "origem": "texto"}},
    "_meta": {"paginas_validacao": ["https://exemplo/ref"]},
}
CANDIDATA_SOBREAJUSTADA = {  # conserta a página que falhou e zera a de referência
    "seletor_item": "li.card",
    "campos": {"titulo": {"seletor": ".clamp1", "origem": "texto"}},
    "_meta": {"paginas_validacao": ["https://exemplo/ref"]},
}
CANDIDATA_QUE_GENERALIZA = {  # agnóstica: serve as duas
    "seletor_item": "li.card",
    "campos": {"titulo": {"seletor": "a.link div", "origem": "texto"}},
    "_meta": {"paginas_validacao": ["https://exemplo/ref"]},
}


def _buscar_fake(_url: str) -> str:
    return PAGINA_DE_REFERENCIA


def test_reparo_sobreajustado_e_RECUSADO_mesmo_pontuando_mais_alto(monkeypatch):
    """O caso real de 23/07, em miniatura.

    Na página que falhou, a candidata pontua 1,0 contra 0,0 da receita atual; olhando
    só essa página, ela seria aceita. Mas ela zera a página de referência, e a receita
    vale para o domínio inteiro. Em produção, ela consertaria 1 vitrine e quebraria 21.
    """
    monkeypatch.setattr(supervisor, "_pedir_reparo",
                        lambda *a, **k: CANDIDATA_SOBREAJUSTADA)
    r = supervisor.reparar(PAGINA_QUE_FALHOU, RECEITA_CLAMP3, CAMPOS_T,
                           "https://exemplo/falhou", max_tentativas=1, buscar_html=_buscar_fake)
    assert r["receita"] == RECEITA_CLAMP3, "a candidata sobreajustada não podia ser aceita"
    assert r["historico"][-1]["aceita"] is False
    assert "regressao_em_referencia" in r["historico"][-1]


def test_reparo_que_generaliza_e_ACEITO(monkeypatch):
    """O contraste que mostra que a proteção não recusa tudo: a candidata que serve
    as duas páginas entra."""
    monkeypatch.setattr(supervisor, "_pedir_reparo",
                        lambda *a, **k: CANDIDATA_QUE_GENERALIZA)
    r = supervisor.reparar(PAGINA_QUE_FALHOU, RECEITA_CLAMP3, CAMPOS_T,
                           "https://exemplo/falhou", max_tentativas=1, buscar_html=_buscar_fake)
    assert r["receita"] == CANDIDATA_QUE_GENERALIZA
    assert r["historico"][-1]["aceita"] is True


def test_sem_paginas_de_referencia_o_comportamento_antigo_e_preservado(monkeypatch):
    """Receita que não declara `paginas_validacao` continua sendo julgada só pela
    página do reparo; nenhuma receita sem essa declaração muda de comportamento."""
    receita_sem_ref = {"seletor_item": "li.card",
                       "campos": {"titulo": {"seletor": ".clamp3", "origem": "texto"}}}
    candidata = {"seletor_item": "li.card",
                 "campos": {"titulo": {"seletor": ".clamp1", "origem": "texto"}}}
    monkeypatch.setattr(supervisor, "_pedir_reparo", lambda *a, **k: candidata)
    r = supervisor.reparar(PAGINA_QUE_FALHOU, receita_sem_ref, CAMPOS_T,
                           "https://exemplo/falhou", max_tentativas=1, buscar_html=_buscar_fake)
    assert r["receita"] == candidata
    assert r["validacao_multipagina"]["paginas"] == []


def test_pagina_de_referencia_que_nao_carrega_e_registrada_e_pulada(monkeypatch):
    """Fonte fora do ar não pode impedir o conserto, mas o fato fica no relatório,
    para que não se suponha que a validação multi-página ocorreu quando não ocorreu."""
    def _falha(_url):
        raise ConnectionError("503")

    monkeypatch.setattr(supervisor, "_pedir_reparo", lambda *a, **k: CANDIDATA_SOBREAJUSTADA)
    r = supervisor.reparar(PAGINA_QUE_FALHOU, RECEITA_CLAMP3, CAMPOS_T,
                           "https://exemplo/falhou", max_tentativas=1, buscar_html=_falha)
    assert r["validacao_multipagina"]["conferidas"] == []
    assert r["validacao_multipagina"]["nao_carregaram"] == ["https://exemplo/ref: ConnectionError"]
    assert r["receita"] == CANDIDATA_SOBREAJUSTADA  # sem referência, vale só a página do reparo


def test_referencia_e_baixada_UMA_vez_so_por_reparo(monkeypatch):
    """Politeness: 3 tentativas de reparo não podem virar 3 downloads da mesma página."""
    chamadas = []

    def _conta(url):
        chamadas.append(url)
        return PAGINA_DE_REFERENCIA

    monkeypatch.setattr(supervisor, "_pedir_reparo", lambda *a, **k: CANDIDATA_SOBREAJUSTADA)
    supervisor.reparar(PAGINA_QUE_FALHOU, RECEITA_CLAMP3, CAMPOS_T,
                       "https://exemplo/falhou", max_tentativas=3, buscar_html=_conta)
    assert len(chamadas) == 1
