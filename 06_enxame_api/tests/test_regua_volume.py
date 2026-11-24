"""A régua de volume (desde 04/08/2026).

Por que este arquivo existe
---------------------------
O detector de bloqueio decidia por marcador: captcha, HTTP >= 400, página curta demais,
título de erro. Entre 23 e 28/07 o Mercado Livre serviu uma página sem marcador algum
(133.957 caracteres, `<title>` legítimo, nenhum produto), e o `conferir()` de produção
a aprovava. O coletor então acionaria o Agente 4 para reparar uma receita intacta,
gastando LLM numa página vazia, que é o que o `bloqueio.py` existe para impedir
(medido em 31/07 contra o HTML gravado).

O que estes testes fixam
------------------------
1. A casca é reprovada e a página saudável passa: o mesmo user-agent, a mesma URL,
   quatro dias de diferença, os dois HTML versionados no repositório.
2. A faixa entre uma e outra é vazia por larga margem, e o piso fica no meio dela.
3. A régua não reprova a variação legítima, medida na série inteira e nos dois
   domínios, porque a régua vale para ambos e foi validada em ambos antes de ir
   para produção.
4. O caminho do reparo continua intacto: página boa, volume normal e campos vazios
   seguem acionando o Agente 4. A régua tira do reparo só os casos que ele não tem
   como consertar.

Os números são exatos porque as entradas são imutáveis: HTML versionado em
`02_Dados/raw/` e as medições de série declaradas em `receitas/_volume_esperado.json`
com a data ao lado. Se algum desses números mudar, mudou a régua, que é o que se quer monitorar.
"""

import json
from pathlib import Path

import pytest

from app import bloqueio

RAW = Path(__file__).resolve().parent.parent.parent / "02_Dados" / "raw"
DADOS = Path(__file__).resolve().parent.parent / "receitas" / "_volume_esperado.json"

ML = "www.mercadolivre.com.br"
AMAZON = "www.amazon.com.br"
URL_ML = "https://www.mercadolivre.com.br/mais-vendidos/"

# A casca de 25/07 (fonte bloqueada) e a página saudável de 29/07 (fonte reaberta),
# as duas servidas ao mesmo user-agent EnxameBot, na mesma URL.
CASCA = RAW / "sonda_rotas_ml_20260725" / "20260725T042037Z_ml_mais-vendidos-rota-atual-quebrada-.html"
SAUDAVEL = RAW / "sonda_reabertura_ml_20260729" / "20260729T020816Z_ml_mais-vendidos_EnxameBot.html"
AMAZON_TOYS = RAW / "experimento_cracha" / "20260725T032517Z_amazon_toys_EnxameBot.html"


def _html(caminho: Path) -> str:
    if not caminho.exists():  # pragma: no cover
        pytest.skip(f"HTML versionado ausente: {caminho}")
    return caminho.read_text(encoding="utf-8", errors="replace")


def _piso_bytes(dominio: str) -> int:
    return bloqueio.volume_esperado(dominio)["piso_bytes"]


# ---------------------------------------------------------------------------
# 1. O caso que motivou a régua: a casca do Mercado Livre
# ---------------------------------------------------------------------------


def test_a_casca_do_ML_PASSAVA_pelo_detector_antigo():
    """O ponto de partida, fixado em teste: o problema é real, não hipotético.

    Sem piso de domínio, o `conferir()` aprova 133.957 caracteres sem um produto:
    não há marcador, o status é 200, o HTML tem 26 vezes o limiar universal e o
    título é legítimo. Por isso a régua de volume foi criada.
    """
    bloqueio.conferir(URL_ML, _html(CASCA), 200)  # não levanta, e esse é o defeito


def test_a_casca_do_ML_e_reprovada_pela_regua_de_volume():
    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        bloqueio.conferir(URL_ML, _html(CASCA), 200, piso_bytes=_piso_bytes(ML))
    assert "casca" in erro.value.motivo


def test_a_pagina_saudavel_do_ML_passa_com_o_MESMO_piso():
    """A outra metade: sem ela, a régua poderia simplesmente recusar tudo."""
    bloqueio.conferir(URL_ML, _html(SAUDAVEL), 200, piso_bytes=_piso_bytes(ML))


def test_entre_a_casca_e_a_pagina_boa_existe_uma_faixa_vazia():
    """O piso não é arbitrário: ele fica no meio de uma faixa onde não há dado.

    É o mesmo critério do piso de 0,5 da régua de campos, que "cai no meio de uma
    faixa vazia" entre o pior campo real e o segundo pior.
    """
    casca, saudavel = len(_html(CASCA)), len(_html(SAUDAVEL))
    piso = _piso_bytes(ML)
    assert casca < piso < saudavel
    assert piso / casca > 1.5, "o piso precisa de folga sobre a casca observada"
    assert saudavel / piso > 1.5, "o piso precisa de folga sob a página saudável"


def test_a_pagina_boa_da_amazon_passa_com_o_piso_dela():
    bloqueio.conferir(
        "https://www.amazon.com.br/gp/bestsellers/toys/",
        _html(AMAZON_TOYS),
        200,
        piso_bytes=_piso_bytes(AMAZON),
    )


# ---------------------------------------------------------------------------
# 2. A segunda metade: a página veio inteira e quase sem item
# ---------------------------------------------------------------------------


def test_vitrine_com_1_item_de_50_e_reprovada():
    """O caso real da `office` (17/07): 1 de 50, e a régua de campos aprovava.

    Ela aprovava com razão, dentro do que mede: 1 item com todos os campos
    preenchidos dá 100%. Proporção não é volume, e é essa lacuna que esta régua cobre.
    """
    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        bloqueio.conferir_volume("https://www.amazon.com.br/gp/bestsellers/office/", 1, 50)
    assert "piso" in erro.value.motivo


def test_a_menor_rodada_LEGITIMA_de_cada_dominio_passa():
    """A régua vale para os dois domínios, então é medida nos dois.

    Os mínimos são medidos, não supostos: 868 pares (vitrine, rodada) na Amazon e
    70 rodadas no ML, na Bronze de 04/08. A variação legítima máxima observada é de
    2% na Amazon (uma vitrine com 49 em vez de 50) e 4% no ML (151 contra mediana 158).
    """
    bloqueio.conferir_volume("https://www.amazon.com.br/gp/bestsellers/toys/", 49, 50)
    bloqueio.conferir_volume(URL_ML, 151, 157)


def test_zero_itens_tambem_e_barrado_quando_ha_expectativa():
    with pytest.raises(bloqueio.PaginaBloqueada):
        bloqueio.conferir_volume(URL_ML, 0, 157)


def test_dominio_sem_medicao_nao_ganha_piso_inventado():
    """Fail-open declarado: domínio novo roda sem régua de volume até ser medido.

    O contrário seria validar num alvo e aplicar em todos. Um piso genérico na régua
    de campos, validado só na Amazon, teria reprovado a receita correta do ML.
    """
    bloqueio.conferir_volume("https://dominio.novo/", 1, None)
    assert bloqueio.volume_esperado("dominio.novo") == {}


def test_arquivo_de_volume_ausente_nao_derruba_a_coleta(tmp_path):
    assert bloqueio.volume_esperado(ML, arquivo=tmp_path / "nao_existe.json") == {}


def test_o_piso_em_itens_e_metade_do_esperado():
    assert bloqueio.piso_de_itens(50, 0.5) == 25
    assert bloqueio.piso_de_itens(157, 0.5) == 78


# ---------------------------------------------------------------------------
# 3. O dado: o piso fica fora do código, e o teste também monitora o dado
# ---------------------------------------------------------------------------


def test_a_receita_de_producao_extrai_162_itens_da_pagina_saudavel_e_ZERO_da_casca():
    """Regressão contra as entradas versionadas, que resume o propósito da régua.

    A mesma receita, a mesma URL, o mesmo user-agent: 0 itens na casca de 25/07 e 162
    na página de 29/07. Esse par mostra que a régua mede o que precisa, e que o piso
    de 78 itens fica longe dos dois lados.
    """
    from app import coletor
    from app.agentes import analista_estrutura as ae

    receita = coletor.carregar_receita_mais_recente(ML)
    assert receita is not None, "sem receita do ML em disco não há o que medir"

    assert len(ae.aplicar_receita(_html(CASCA), receita)) == 0
    assert len(ae.aplicar_receita(_html(SAUDAVEL), receita)) == 162


def test_a_casca_aborta_a_coleta_INTEIRA_sem_chamar_o_llm(monkeypatch):
    """Ponta a ponta, onde o defeito se manifestava: sem a régua, isto acionaria o Agente 4.

    Sem a régua, a sequência é: a casca passa pelo `conferir()`, a receita (intacta)
    extrai 0 itens, a régua de campos reprova, o Supervisor é chamado e o LLM é usado
    numa página sem produto. Com a régua, a coleta aborta antes, e o teste falha de
    propósito se o LLM for chamado.
    """
    from app import coleta_http, coletor
    from app.agentes import analista_estrutura, conformidade

    conformidade.limpar_cache()
    monkeypatch.setattr(
        coletor.conformidade, "verificar",
        lambda url, ua: conformidade.Veredito(True, "ok", "r", crawl_delay=None),
    )

    class _Resposta:
        text = _html(CASCA)
        url = URL_ML
        status_code = 200

    monkeypatch.setattr(coleta_http.httpx, "get", lambda *a, **kw: _Resposta())
    monkeypatch.setattr(
        analista_estrutura, "_chamar_llm",
        lambda m, **kw: (_ for _ in ()).throw(AssertionError("casca não pode acionar o LLM")),
    )

    with pytest.raises(bloqueio.PaginaBloqueada) as erro:
        coletor.coletar(URL_ML, None, "http", "EnxameBot/0.1")
    assert "casca" in erro.value.motivo


def test_SEM_a_regua_a_mesma_casca_chegaria_ao_LLM(monkeypatch):
    """O controle negativo, sem o qual o teste acima não demonstra nada.

    Desligando a régua (domínio sem medição), a mesma página percorre o caminho até o
    Agente 4. O `AssertionError` que sobe aqui é a chamada de LLM que a régua impede.
    """
    from app import coleta_http, coletor
    from app.agentes import analista_estrutura, conformidade

    conformidade.limpar_cache()
    monkeypatch.setattr(
        coletor.conformidade, "verificar",
        lambda url, ua: conformidade.Veredito(True, "ok", "r", crawl_delay=None),
    )
    monkeypatch.setattr(coletor.bloqueio, "volume_esperado", lambda dom: {})

    class _Resposta:
        text = _html(CASCA)
        url = URL_ML
        status_code = 200

    monkeypatch.setattr(coleta_http.httpx, "get", lambda *a, **kw: _Resposta())
    monkeypatch.setattr(
        analista_estrutura, "_chamar_llm",
        lambda m, **kw: (_ for _ in ()).throw(AssertionError("aqui o LLM É chamado")),
    )

    with pytest.raises(AssertionError, match="aqui o LLM É chamado"):
        coletor.coletar(URL_ML, None, "http", "EnxameBot/0.1")


def test_os_dois_dominios_em_producao_tem_regua_declarada():
    dados = json.loads(DADOS.read_text(encoding="utf-8"))
    assert set(dados["dominios"]) == {ML, AMAZON}
    for dominio, regra in dados["dominios"].items():
        assert regra["piso_bytes"] > bloqueio.LIMIAR_HTML_CURTO, dominio
        assert 0 < regra["piso_fracao"] < 1, dominio
        assert regra["itens_esperados"] > 0, dominio


def test_o_piso_declarado_fica_abaixo_de_toda_pagina_saudavel_medida():
    """Confere o dado contra a evidência que ele próprio carrega.

    Se o piso for elevado sem nova medição, este teste falha e informa o motivo.
    """
    dados = json.loads(DADOS.read_text(encoding="utf-8"))["dominios"]
    for dominio, regra in dados.items():
        saudaveis = regra["evidencia"]["bytes_saudavel"]
        assert regra["piso_bytes"] < min(saudaveis), (
            f"{dominio}: piso {regra['piso_bytes']} encosta na menor página saudável "
            f"medida ({min(saudaveis)})"
        )
        for degradada in regra["evidencia"].get("bytes_casca", []) + regra["evidencia"].get("bytes_erro", []):
            assert degradada < regra["piso_bytes"], f"{dominio}: {degradada} escaparia"
