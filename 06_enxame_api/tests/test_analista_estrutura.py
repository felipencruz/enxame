"""Testes do Agente 2, sem rede e sem LLM (a resposta do modelo é simulada)."""

from app.agentes import analista_estrutura

HTML_EXEMPLO = """
<html><head><script>alert('fora!')</script><style>.x{}</style></head><body>
<ul class="vitrine">
  <li class="produto"><h2 class="nome">Tênis Corrida Azul</h2>
      <span class="preco">R$ 199,90</span>
      <a class="link" href="/p/tenis-azul">ver</a></li>
  <li class="produto"><h2 class="nome">Tênis Trilha Verde</h2>
      <span class="preco">R$ 249,00</span>
      <a class="link" href="/p/tenis-verde">ver</a></li>
  <li class="produto"><h2 class="nome">Tênis Casual Preto</h2>
      <a class="link" href="/p/tenis-preto">ver</a></li>
</ul></body></html>
"""

RECEITA_EXEMPLO = {
    "seletor_item": "li.produto",
    "campos": {
        "titulo": {"seletor": "h2.nome", "origem": "texto"},
        "preco": {"seletor": "span.preco", "origem": "texto"},
        "link": {"seletor": "a.link", "origem": "atributo", "atributo": "href"},
    },
}

CAMPOS = [{"nome": "titulo"}, {"nome": "preco"}, {"nome": "link"}]


def test_limpar_html_remove_scripts_e_estilos():
    limpo = analista_estrutura.limpar_html(HTML_EXEMPLO)
    assert "alert" not in limpo
    assert "<style>" not in limpo
    assert "Tênis Corrida Azul" in limpo


def test_aplicar_receita_extrai_deterministicamente():
    linhas = analista_estrutura.aplicar_receita(HTML_EXEMPLO, RECEITA_EXEMPLO)
    assert len(linhas) == 3
    assert linhas[0] == {
        "titulo": "Tênis Corrida Azul",
        "preco": "R$ 199,90",
        "link": "/p/tenis-azul",
    }
    assert linhas[2]["preco"] is None  # produto sem preço não inventa valor


def test_validar_receita_mede_preenchimento():
    linhas = analista_estrutura.aplicar_receita(HTML_EXEMPLO, RECEITA_EXEMPLO)
    validacao = analista_estrutura.validar_receita(linhas, CAMPOS)
    assert validacao["itens_encontrados"] == 3
    assert validacao["campos"]["titulo"]["taxa"] == 1.0
    assert validacao["campos"]["preco"]["preenchidos"] == 2


def test_seletor_invalido_nao_derruba_a_extracao():
    receita = {"seletor_item": "li.produto", "campos": {"x": {"seletor": ":::???", "origem": "texto"}}}
    linhas = analista_estrutura.aplicar_receita(HTML_EXEMPLO, receita)
    assert all(l["x"] is None for l in linhas)


def test_propor_receita_anexa_metadados(monkeypatch):
    monkeypatch.setattr(analista_estrutura, "_chamar_llm", lambda mensagens, **kw: dict(RECEITA_EXEMPLO))
    receita = analista_estrutura.propor_receita(HTML_EXEMPLO, CAMPOS, "https://exemplo.com.br/busca")
    assert receita["seletor_item"] == "li.produto"
    meta = receita["_meta"]
    assert meta["dominio"] == "exemplo.com.br"
    assert meta["agente"] == "analista_estrutura"


def test_propor_receita_guarda_o_pedido_no_meta(monkeypatch):
    """O pedido (nome e descrição de cada campo) fica junto da receita, porque a
    coleta agendada só conhece a receita salva, e no reparo o Analista precisa da
    descrição para acertar (0,984 com ela, 0,167 sem: medido na Amazon em 15/07)."""
    monkeypatch.setattr(
        analista_estrutura, "_chamar_llm",
        lambda mensagens, **kw: {"seletor_item": "li", "campos": {"titulo": {"seletor": "h2", "origem": "texto"}}},
    )
    campos = [
        {"nome": "titulo", "descricao": "nome do produto", "tipo": "texto"},
        {"nome": "preco"},
    ]
    receita = analista_estrutura.propor_receita("<ul><li><h2>x</h2></li></ul>", campos, "https://x.com/l")

    # O pedido guarda descrição (para o LLM no reparo) e tipo (para a régua do Agente 3).
    assert receita["_meta"]["campos_pedidos"] == [
        {"nome": "titulo", "descricao": "nome do produto", "tipo": "texto"},
        {"nome": "preco", "descricao": "", "tipo": None},
    ]
