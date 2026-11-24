"""Régua de aceite da receita: quem decide o que vai para produção é o código.

O endpoint `/agentes/analista/propor-receita` salva a receita mesmo reprovada,
como evidência. Se o carregador pegasse sempre a mais recente do domínio sem olhar
a qualidade, uma proposta alucinada viraria a receita da próxima coleta agendada.
Exemplo real no repositório: `receitas/lista.mercadolivre.com.br/receita_20260713_204621.json`,
com `seletor_item: ".item-class"`: o LLM inventou um seletor genérico ao receber a
página anti-bot do ML, que deu 0 itens (15/07).
"""

import json

import pytest

from app import coletor
from app.agentes import analista_estrutura as ae

VAL_BOA = {"itens_encontrados": 20, "campos": {"titulo": {"preenchidos": 20, "taxa": 1.0}}}
VAL_SEM_ITENS = {"itens_encontrados": 0, "campos": {"titulo": {"preenchidos": 0, "taxa": 0.0}}}
VAL_ITENS_VAZIOS = {"itens_encontrados": 36, "campos": {"titulo": {"preenchidos": 0, "taxa": 0.0}}}


def test_receita_sem_itens_e_reprovada():
    assert ae.aprovada(VAL_SEM_ITENS) is False


def test_receita_com_itens_mas_nenhum_campo_preenchido_e_reprovada():
    """Achar 36 itens vazios não é extrair: casou o item e nenhum campo."""
    assert ae.aprovada(VAL_ITENS_VAZIOS) is False


def test_receita_que_extrai_e_aprovada():
    assert ae.aprovada(VAL_BOA) is True


def test_salvar_carimba_o_veredito_no_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(ae.config, "DIR_RECEITAS", tmp_path)
    receita = {"seletor_item": "li", "campos": {}, "_meta": {"dominio": "x.com"}}
    caminho = ae.salvar_receita(receita, VAL_SEM_ITENS)
    salva = json.loads(open(caminho, encoding="utf-8").read())
    assert salva["_meta"]["aprovada"] is False
    assert salva["_meta"]["validacao"]["itens_encontrados"] == 0


def test_salvo_em_e_do_momento_da_gravacao_e_nao_herda_o_criado_em(tmp_path, monkeypatch):
    """O `criado_em` do Analista é herdado pela receita reparada e não indica a gravação.

    Caso real que motivou o campo (auditoria de 25/07/2026): as três receitas de
    23/07 da Amazon em produção têm `_meta.criado_em = 2026-07-16T01:36:18`,
    herdado de `receita_20260716_013618.json`, enquanto o nome do arquivo diz
    `20260723`. Como as receitas versionadas são a trilha de auditoria, cada
    artefato precisa do carimbo da própria gravação.
    """
    monkeypatch.setattr(ae.config, "DIR_RECEITAS", tmp_path)
    receita = {
        "seletor_item": "li",
        "campos": {},
        "_meta": {"dominio": "x.com", "criado_em": "2020-01-01T00:00:00+00:00"},
    }
    salva = json.loads(open(ae.salvar_receita(receita, VAL_BOA), encoding="utf-8").read())
    assert salva["_meta"]["criado_em"] == "2020-01-01T00:00:00+00:00", "criado_em é do Analista"
    assert salva["_meta"]["salvo_em"] > "2026", "salvo_em é desta gravação"


def test_o_historico_do_reparo_fica_no_artefato(tmp_path, monkeypatch):
    """A evidência de que o sistema se reparou sozinho tem de ficar em disco.

    `supervisor.reparar` devolve o `historico` (pontuação antes e depois, tentativas
    e as regressões em página de referência que barraram uma candidata). Desde
    25/07 esse histórico é gravado no artefato, e não só a validação. É a evidência
    central do auto-reparo, usada na monografia e na defesa.
    """
    monkeypatch.setattr(ae.config, "DIR_RECEITAS", tmp_path)
    resultado_reparo = {
        "pontuacao": 0.944,
        "tentativas": 2,
        "historico": [
            {"tentativa": 0, "pontuacao": 0.816, "problemas": ["titulo em 18%"]},
            {"tentativa": 1, "pontuacao": 0.944, "aceita": True},
            {"tentativa": 2, "pontuacao": 0.95, "aceita": False,
             "regressao_em_referencia": {"https://x/ref": (0.9, 0.1)}},
        ],
        "validacao_multipagina": {"https://x/ref": 0.9},
    }
    caminho = ae.salvar_receita(
        {"seletor_item": "li", "campos": {}, "_meta": {"dominio": "x.com"}},
        VAL_BOA,
        reparo=resultado_reparo,
    )
    reparo = json.loads(open(caminho, encoding="utf-8").read())["_meta"]["reparo_historico"]
    assert reparo["pontuacao_inicial"] == 0.816
    assert reparo["pontuacao_final"] == 0.944
    assert reparo["tentativas"] == 2
    assert len(reparo["historico"]) == 3
    # A candidata recusada por regredir na referência é parte da evidência: é ela
    # que mostra a proteção contra sobreajuste em ação.
    assert "regressao_em_referencia" in reparo["historico"][2]


def test_o_flag_reparo_booleano_do_supervisor_nao_e_sobrescrito(tmp_path, monkeypatch):
    """`_meta.reparo` é bool desde 23/07 e está assim nos artefatos versionados.

    O histórico foi para uma chave própria justamente para não trocar o tipo de um
    campo já presente na trilha de auditoria. Este teste fixa a coexistência.
    """
    monkeypatch.setattr(ae.config, "DIR_RECEITAS", tmp_path)
    caminho = ae.salvar_receita(
        {"seletor_item": "li", "_meta": {"dominio": "x.com", "agente": "supervisor", "reparo": True}},
        VAL_BOA,
        reparo={"pontuacao": 0.9, "tentativas": 1, "historico": [{"pontuacao": 0.5}]},
    )
    meta = json.loads(open(caminho, encoding="utf-8").read())["_meta"]
    assert meta["reparo"] is True, "o flag booleano do supervisor sobrevive"
    assert meta["reparo_historico"]["pontuacao_final"] == 0.9


def test_receita_sem_reparo_nao_ganha_o_bloco_de_historico(tmp_path, monkeypatch):
    """Receita proposta de primeira não pode parecer reparada."""
    monkeypatch.setattr(ae.config, "DIR_RECEITAS", tmp_path)
    caminho = ae.salvar_receita({"seletor_item": "li", "_meta": {"dominio": "x.com"}}, VAL_BOA)
    meta = json.loads(open(caminho, encoding="utf-8").read())["_meta"]
    assert "reparo_historico" not in meta
    assert "reparo" not in meta


def test_receita_reprovada_continua_sendo_salva_como_evidencia(tmp_path, monkeypatch):
    """O erro do LLM não é apagado: ele é material de apêndice."""
    monkeypatch.setattr(ae.config, "DIR_RECEITAS", tmp_path)
    ae.salvar_receita({"seletor_item": ".item-class", "_meta": {"dominio": "x.com"}}, VAL_SEM_ITENS)
    assert len(list((tmp_path / "x.com").glob("receita_*.json"))) == 1


def test_carregador_ignora_a_reprovada_e_pega_a_aprovada_anterior(tmp_path, monkeypatch):
    """O caso central: a reprovada é a mais recente e, mesmo assim, não pode entrar."""
    monkeypatch.setattr(coletor.config, "DIR_RECEITAS", tmp_path)
    pasta = tmp_path / "x.com"
    pasta.mkdir()
    (pasta / "receita_20260101_000000.json").write_text(
        json.dumps({"seletor_item": "li.bom", "_meta": {"aprovada": True}}), encoding="utf-8")
    (pasta / "receita_20260202_000000.json").write_text(
        json.dumps({"seletor_item": ".item-class", "_meta": {"aprovada": False}}), encoding="utf-8")

    receita = coletor.carregar_receita_mais_recente("x.com")
    assert receita["seletor_item"] == "li.bom"


def test_carregador_devolve_none_se_todas_reprovadas(tmp_path, monkeypatch):
    monkeypatch.setattr(coletor.config, "DIR_RECEITAS", tmp_path)
    pasta = tmp_path / "x.com"
    pasta.mkdir()
    (pasta / "receita_20260101_000000.json").write_text(
        json.dumps({"seletor_item": ".item-class", "_meta": {"aprovada": False}}), encoding="utf-8")
    assert coletor.carregar_receita_mais_recente("x.com") is None


def test_receita_antiga_sem_o_campo_aprovada_continua_valendo(tmp_path, monkeypatch):
    """Compatibilidade: as receitas salvas antes desta marcação não têm o campo."""
    monkeypatch.setattr(coletor.config, "DIR_RECEITAS", tmp_path)
    pasta = tmp_path / "x.com"
    pasta.mkdir()
    (pasta / "receita_20260101_000000.json").write_text(
        json.dumps({"seletor_item": "li.antigo", "_meta": {"dominio": "x.com"}}), encoding="utf-8")
    assert coletor.carregar_receita_mais_recente("x.com")["seletor_item"] == "li.antigo"


def test_a_receita_alucinada_do_ml_esta_marcada_no_repositorio():
    """Regressão sobre o artefato real: o teste falha se aquele arquivo for reabilitado."""
    receita = coletor.carregar_receita_mais_recente("lista.mercadolivre.com.br")
    assert receita is None, "a receita '.item-class' (0 itens) jamais pode ser carregada"


# --- Régua por média dos campos (15/07/2026) ---------------------------------
#
# Caso real: pedimos ao Agente 2 a receita do layout de departamento da Amazon
# (/gp/bestsellers/toys/). Ele acertou o seletor_item (50 itens) e o link (100%),
# e errou os outros cinco campos (0%). Uma régua do tipo "achou itens e preencheu
# ao menos 1 campo" aprovaria essa receita, e um gatilho de reparo só com zero
# itens não acionaria o Agente 4: a coleta colheria só links a cada 6h com
# `llm_usado: false`.
#
# Os números abaixo são os medidos naquele dia.

VAL_SO_LINK = {   # a proposta real do Agente 2 para o layout de departamento
    "itens_encontrados": 50,
    "campos": {
        "titulo": {"preenchidos": 0, "taxa": 0.0},
        "preco": {"preenchidos": 0, "taxa": 0.0},
        "link": {"preenchidos": 50, "taxa": 1.0},
        "rank": {"preenchidos": 0, "taxa": 0.0},
        "avaliacao": {"preenchidos": 0, "taxa": 0.0},
    },
}
RECEITA_SO_LINK = {
    "seletor_item": ".zg-grid-general-faceout",
    "campos": {
        "titulo": {"seletor": "a > div > div > a > div", "origem": "texto"},
        "preco": {"seletor": "a > div > div > a > div.a-row > a > span", "origem": "texto"},
        "link": {"seletor": "a", "origem": "atributo", "atributo": "href"},
        "rank": {"seletor": ".zg-bdg-text", "origem": "texto"},
        "avaliacao": {"seletor": "a > div > div > div.a-row > div > a", "origem": "atributo"},
    },
    "_meta": {"dominio": "www.amazon.com.br"},
}

VAL_DEPT_BOA = {  # a proposta do Agente 2 quando recebe `descricao` nos campos
    "itens_encontrados": 50,
    "campos": {
        "titulo": {"preenchidos": 47, "taxa": 0.94},
        "preco": {"preenchidos": 50, "taxa": 1.0},
        "link": {"preenchidos": 50, "taxa": 1.0},
        "rank": {"preenchidos": 50, "taxa": 1.0},
        "avaliacao": {"preenchidos": 49, "taxa": 0.98},
    },
}

# Receita da rota aposentada da Amazon (página geral, até 16/07): `preco` é null de
# propósito, pois a fonte não servia preço a quem se identifica como robô naquela
# rota (medido). Usada aqui como exemplo de que campo ausente confirmado não pode
# reprovar receita correta. A rota atual (departamentos, desde 16/07) tem preço e
# não passa por este caso. Ver 01_Coleta_n8n para a rota em uso.
VAL_GERAL_AMAZON = {
    "itens_encontrados": 36,
    "campos": {
        "categoria": {"preenchidos": 36, "taxa": 1.0},
        "titulo": {"preenchidos": 36, "taxa": 1.0},
        "preco": {"preenchidos": 0, "taxa": 0.0},
        "link": {"preenchidos": 36, "taxa": 1.0},
        "rank": {"preenchidos": 36, "taxa": 1.0},
        "avaliacao": {"preenchidos": 36, "taxa": 1.0},
    },
}
RECEITA_GERAL_AMAZON = {
    "seletor_item": ".a-carousel-card",
    "seletor_grupo": ".a-carousel-container",
    "campos_grupo": {"categoria": {"seletor": ".a-carousel-heading", "origem": "texto"}},
    "campos": {
        "titulo": {"seletor": ".p13n-sc-truncate", "origem": "texto"},
        "preco": None,   # prompt do Analista: campo inexistente é mapeado como null
        "link": {"seletor": "a.a-link-normal", "origem": "atributo", "atributo": "href"},
        "rank": {"seletor": ".zg-bdg-text", "origem": "texto"},
        "avaliacao": {"seletor": ".a-icon-row a", "origem": "atributo"},
    },
    "_meta": {"dominio": "www.amazon.com.br",
              "campos_ausentes": {"preco": "a fonte não publica preço para o EnxameBot nesta rota"}},
}


def test_receita_que_le_um_campo_de_cinco_e_reprovada():
    """O caso real: 50 itens, só o link. Uma régua por "ao menos 1 campo" aprovaria isto."""
    assert ae.aprovada(VAL_SO_LINK, RECEITA_SO_LINK) is False


def test_receita_de_departamento_boa_e_aprovada():
    assert ae.aprovada(VAL_DEPT_BOA, None) is True


def test_campo_ausente_na_fonte_nao_reprova_receita_correta():
    """`preco` é null de propósito na página geral da Amazon: a fonte não o serve.
    Cobrar por ele reprovaria a receita que está em produção e funciona."""
    assert ae.aprovada(VAL_GERAL_AMAZON, RECEITA_GERAL_AMAZON) is True


def test_sem_a_receita_a_regua_cobra_todos_os_campos():
    """Sem o contexto da receita não dá para saber o que é ausência legítima,
    então `preco` entra na conta. Aqui o veredito não muda (5 campos perfeitos de
    6 = 0,83, acima do limiar), mas o denominador muda, e isso pesa numa receita com
    mais campos ausentes."""
    assert len(ae.campos_cobraveis(VAL_GERAL_AMAZON, RECEITA_GERAL_AMAZON)) == 5
    assert len(ae.campos_cobraveis(VAL_GERAL_AMAZON)) == 6
    assert ae.aprovada(VAL_GERAL_AMAZON) is True


def test_metade_dos_campos_e_o_limiar():
    """O limiar é o mesmo TAXA_CAMPO_RUIM que o Supervisor usa para considerar um
    campo defeituoso, e não um número novo."""
    val = {"itens_encontrados": 10, "campos": {
        "a": {"preenchidos": 10, "taxa": 1.0},
        "b": {"preenchidos": 0, "taxa": 0.0},
    }}
    assert ae.TAXA_CAMPO_RUIM == 0.5
    assert ae.aprovada(val) is True     # média exatamente 0,5: passa no limite

    val["campos"]["c"] = {"preenchidos": 0, "taxa": 0.0}
    assert ae.aprovada(val) is False    # média 0,33: reprovada


# ---------------------------------------------------------------------------
# Campo essencial (desde 22/07): resolve a limitação "todos os campos têm o mesmo
# peso", observada em produção
# ---------------------------------------------------------------------------


def _val_games_e_consoles():
    """O caso real: vitrine Games e Consoles da Amazon, medida em 22/07.

    O seletor do `titulo` fixava `line-clamp-3` e aqueles cards renderizam o título
    em `line-clamp-1`, o que deu 18% de preenchimento. Todo o resto vinha perfeito,
    e a média dos 5 campos dava 0,82: a régua aprovava, o Agente 4 não era acionado,
    e o defeito persistiu por 6 dias.
    """
    return {"itens_encontrados": 50, "campos": {
        "titulo": {"preenchidos": 9, "taxa": 0.18, "validos": 9, "taxa_valida": 0.18, "tipo": "texto"},
        "preco": {"preenchidos": 50, "taxa": 1.0, "validos": 50, "taxa_valida": 1.0, "tipo": "preco"},
        "avaliacao": {"preenchidos": 50, "taxa": 1.0, "validos": 50, "taxa_valida": 1.0, "tipo": "texto"},
        "link": {"preenchidos": 50, "taxa": 1.0, "validos": 50, "taxa_valida": 1.0, "tipo": "url"},
        "rank": {"preenchidos": 50, "taxa": 1.0, "validos": 50, "taxa_valida": 1.0, "tipo": "rank"},
    }}


def test_regua_antiga_aprovaria_o_defeito_de_games_e_consoles():
    """Regressão no sentido inverso: a média sozinha aprova o defeito. Se a
    reprovação direta do campo essencial for removida, este teste documenta o que se
    perde: 0,82 de média com o título faltando em 82% dos itens."""
    val = _val_games_e_consoles()
    taxas = [c["taxa_valida"] for c in val["campos"].values()]
    assert sum(taxas) / len(taxas) >= ae.TAXA_CAMPO_RUIM


def test_titulo_abaixo_do_piso_reprova_mesmo_com_a_media_alta():
    assert ae.aprovada(_val_games_e_consoles()) is False


def test_titulo_acima_do_piso_passa():
    val = _val_games_e_consoles()
    val["campos"]["titulo"].update({"preenchidos": 50, "taxa": 1.0, "validos": 50, "taxa_valida": 1.0})
    assert ae.aprovada(val) is True


def test_campo_OPCIONAL_esparso_NAO_reprova_a_receita_do_ML():
    """Impede que a regra vire um piso para todo campo.

    No Mercado Livre, `preco_antigo` e `desconto` são legitimamente esparsos: só
    item com desconto os tem. Isso é característica da fonte, não defeito, e um piso
    genérico derrubaria a coleta de um domínio inteiro. Só o campo essencial é
    cobrado.

    Ocupação real desses campos, medida contra a Bronze em 04/08/2026:

    - média de 73,8% nas 39 rodadas até 22/07, janela em que a regra foi escrita (as
      receitas versionadas medem 0,707 e 0,732, uma rodada cada);
    - nessa janela, um piso de 0,5 reprovaria 0 de 39 rodadas (a pior é 0,705); o
      argumento da regra depende de o campo ser esparso, e ele é;
    - na série inteira (66 rodadas): geral de 0,730, faixa de 0,662 a 0,810.

    O caso sintético abaixo usa 0,30 de propósito: ele exercita a regra, não a fonte.
    Fixar aqui a taxa real faria o teste depender do comportamento do mercado.
    """
    val = {"itens_encontrados": 100, "campos": {
        "titulo": {"preenchidos": 100, "taxa": 1.0, "validos": 100, "taxa_valida": 1.0, "tipo": "texto"},
        "preco": {"preenchidos": 100, "taxa": 1.0, "validos": 100, "taxa_valida": 1.0, "tipo": "preco"},
        "preco_antigo": {"preenchidos": 30, "taxa": 0.30, "validos": 30, "taxa_valida": 0.30, "tipo": "preco"},
        "desconto": {"preenchidos": 30, "taxa": 0.30, "validos": 30, "taxa_valida": 0.30, "tipo": "percentual"},
        "link": {"preenchidos": 100, "taxa": 1.0, "validos": 100, "taxa_valida": 1.0, "tipo": "url"},
    }}
    assert ae.aprovada(val) is True


def test_receita_pode_declarar_os_proprios_campos_essenciais():
    val = {"itens_encontrados": 10, "campos": {
        "titulo": {"preenchidos": 10, "taxa": 1.0, "validos": 10, "taxa_valida": 1.0},
        "preco": {"preenchidos": 2, "taxa": 0.2, "validos": 2, "taxa_valida": 0.2},
        "link": {"preenchidos": 10, "taxa": 1.0, "validos": 10, "taxa_valida": 1.0},
    }}
    receita = {"campos": {"titulo": "a", "preco": "b", "link": "c"}}
    assert ae.aprovada(val, receita) is True  # padrão: só `titulo` é essencial
    receita["_meta"] = {"campos_essenciais": ["titulo", "preco"]}
    assert ae.aprovada(val, receita) is False


def test_campo_essencial_ausente_na_fonte_nao_reprova():
    """Se a fonte comprovadamente não serve o campo (`campos_ausentes`), ele nem entra
    nos cobráveis; o piso não pode reintroduzi-lo e derrubar receita correta."""
    val = {"itens_encontrados": 10, "campos": {
        "titulo": {"preenchidos": 0, "taxa": 0.0, "validos": 0, "taxa_valida": 0.0},
        "link": {"preenchidos": 10, "taxa": 1.0, "validos": 10, "taxa_valida": 1.0},
    }}
    receita = {"campos": {"titulo": "a", "link": "c"}, "_meta": {"campos_ausentes": ["titulo"]}}
    assert ae.aprovada(val, receita) is True
