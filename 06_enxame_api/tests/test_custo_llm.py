"""Testes do registro de custo do LLM (29/07/2026), sem rede e sem LLM.

O que estes testes fixam:

- O dólar é derivado; o token é medido. Modelo fora da tabela grava tokens e
  `custo_usd: null`, nunca um valor estimado que pareceria medição.
- Total parcial não é apresentado como total. Se um evento tem preço desconhecido,
  a soma devolve `custo_usd: None` em vez de somar o que houver.
- O log não derruba a coleta. Falha de gravação é avisada e contada, mas não levanta.
- O custo fica em um único campo do artefato (`_meta.custo_llm`), sem cópia dentro
  do `reparo_historico`, para que os dois valores não possam divergir.
"""

import json

import pytest

from app import custo_llm
from app.agentes import analista_estrutura as ae
from app.agentes import supervisor


# --- O cálculo -------------------------------------------------------------

def test_um_milhao_de_tokens_de_entrada_custa_o_preco_de_tabela():
    assert custo_llm.calcular_custo_usd("gpt-4o-mini", 1_000_000, 0) == 0.15


def test_um_milhao_de_tokens_de_saida_custa_o_preco_de_tabela():
    assert custo_llm.calcular_custo_usd("gpt-4o-mini", 0, 1_000_000) == 0.60


def test_token_cacheado_sai_mais_barato_e_nao_e_cobrado_duas_vezes():
    """`prompt_tokens` da OpenAI já inclui os cacheados. Se a conta somasse os dois,
    o mesmo token seria cobrado no preço cheio e no de cache."""
    cheio = custo_llm.calcular_custo_usd("gpt-4o-mini", 1_000_000, 0, tokens_cacheados=0)
    metade = custo_llm.calcular_custo_usd("gpt-4o-mini", 1_000_000, 0, tokens_cacheados=1_000_000)
    assert cheio == 0.15
    assert metade == 0.075  # tudo cacheado: metade do preço, não 0,225


def test_modelo_fora_da_tabela_nao_inventa_preco():
    assert custo_llm.calcular_custo_usd("modelo-que-nao-existe", 1_000, 1_000) is None


def test_snapshot_datado_e_precificado_pela_familia():
    """Comportamento observado em chamada real (29/07/2026): pedimos `gpt-4o-mini` e a
    API responde `gpt-4o-mini-2024-07-18`. Sem o casamento por família, todo evento de
    produção sairia com `custo_usd: null`."""
    assert custo_llm.familia_do_modelo("gpt-4o-mini-2024-07-18") == "gpt-4o-mini"
    assert custo_llm.calcular_custo_usd("gpt-4o-mini-2024-07-18", 1_000_000, 0) == 0.15


def test_evento_guarda_o_nome_cru_e_o_que_precificou():
    """Os dois nomes, porque precificar por família é inferência, não medição, e a
    inferência precisa ficar declarada no registro."""
    evento = custo_llm.montar_evento(
        contexto="supervisor", modelo="gpt-4o-mini-2024-07-18",
        usage={"prompt_tokens": 1_000_000, "completion_tokens": 0}, duracao_s=0.1,
    )
    assert evento["modelo"] == "gpt-4o-mini-2024-07-18"
    assert evento["modelo_familia"] == "gpt-4o-mini"
    assert evento["custo_usd"] == 0.15


def test_evento_de_modelo_desconhecido_se_declara():
    evento = custo_llm.montar_evento(
        contexto="analista_estrutura",
        modelo="modelo-que-nao-existe",
        usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        duracao_s=0.1,
    )
    assert evento["custo_usd"] is None
    assert evento["preco_conhecido"] is False
    assert evento["tokens_total"] == 12


def test_evento_sem_usage_nao_quebra():
    """Resposta sem bloco `usage` (erro da API, proxy) vira linha com zeros: o log
    registra que a chamada existiu, o que evita subestimar a contagem."""
    evento = custo_llm.montar_evento(
        contexto="supervisor", modelo="gpt-4o-mini", usage=None, duracao_s=0.5
    )
    assert evento["tokens_total"] == 0
    assert evento["custo_usd"] == 0.0


# --- O log -----------------------------------------------------------------

def test_log_e_append_only(tmp_path):
    destino = tmp_path / "llm_uso.jsonl"
    for i in range(3):
        custo_llm.registrar(
            custo_llm.montar_evento(
                contexto="supervisor", modelo="gpt-4o-mini",
                usage={"prompt_tokens": i, "completion_tokens": 1}, duracao_s=0.1,
            ),
            caminho=destino,
        )
    linhas = destino.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 3
    assert json.loads(linhas[0])["contexto"] == "supervisor"


def test_falha_de_gravacao_nao_derruba_a_coleta(tmp_path):
    """A única exceção deliberada à falha explícita: perder a rodada de coleta porque
    o log de custo não gravou trocaria um problema contábil por uma lacuna na Bronze,
    que é imutável. A falha não é silenciosa: é contada."""
    antes = custo_llm.FALHAS_DE_GRAVACAO
    arquivo_no_lugar_da_pasta = tmp_path / "bloqueio"
    arquivo_no_lugar_da_pasta.write_text("nao sou pasta", encoding="utf-8")
    evento = custo_llm.registrar(
        custo_llm.montar_evento(
            contexto="supervisor", modelo="gpt-4o-mini",
            usage={"prompt_tokens": 1, "completion_tokens": 1}, duracao_s=0.1,
        ),
        caminho=arquivo_no_lugar_da_pasta / "sub" / "llm.jsonl",
    )
    assert evento["tokens_total"] == 2  # devolveu o evento mesmo sem gravar
    assert custo_llm.FALHAS_DE_GRAVACAO == antes + 1


def test_caminho_do_log_respeita_a_variavel_de_ambiente(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_LOG_PATH", str(tmp_path / "outro.jsonl"))
    assert custo_llm.caminho_log() == tmp_path / "outro.jsonl"


# --- A sessão (o custo de um ciclo) ----------------------------------------

def test_sessao_junta_os_eventos_do_ciclo(tmp_path):
    destino = tmp_path / "l.jsonl"
    with custo_llm.sessao() as eventos:
        for _ in range(2):
            custo_llm.registrar(
                custo_llm.montar_evento(
                    contexto="supervisor", modelo="gpt-4o-mini",
                    usage={"prompt_tokens": 1_000_000, "completion_tokens": 0}, duracao_s=1.0,
                ),
                caminho=destino,
            )
    total = custo_llm.somar(eventos)
    assert total["chamadas"] == 2
    assert total["custo_usd"] == 0.30
    assert total["duracao_s"] == 2.0


def test_fora_da_sessao_nada_e_acumulado(tmp_path):
    destino = tmp_path / "l.jsonl"
    with custo_llm.sessao() as eventos:
        pass
    custo_llm.registrar(
        custo_llm.montar_evento(contexto="x", modelo="gpt-4o-mini", usage={}, duracao_s=0.1),
        caminho=destino,
    )
    assert eventos == []  # a sessão fechou: o evento não vaza para dentro dela


def test_soma_com_preco_desconhecido_nao_finge_total():
    eventos = [
        custo_llm.montar_evento(contexto="a", modelo="gpt-4o-mini",
                                usage={"prompt_tokens": 1_000_000}, duracao_s=0.1),
        custo_llm.montar_evento(contexto="a", modelo="desconhecido",
                                usage={"prompt_tokens": 1_000_000}, duracao_s=0.1),
    ]
    total = custo_llm.somar(eventos)
    assert total["tokens_entrada"] == 2_000_000
    assert total["custo_usd"] is None  # parcial não é total


# --- Integração: quem chama o LLM registra ---------------------------------

class _RespostaFalsa:
    def __init__(self, corpo):
        self._corpo = corpo

    def raise_for_status(self):
        return None

    def json(self):
        return self._corpo


@pytest.fixture
def _llm_falso(monkeypatch, tmp_path):
    """Substitui a rede, não o `_chamar_llm`: é justamente o `_chamar_llm` que
    precisa ser exercido, porque é ele que registra."""
    monkeypatch.setenv("LLM_LOG_PATH", str(tmp_path / "llm_uso.jsonl"))
    monkeypatch.setattr(ae.config, "OPENAI_API_KEY", "chave-de-teste")
    corpo = {
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 30_000, "completion_tokens": 500, "total_tokens": 30_500},
        "choices": [{"message": {"content": json.dumps(
            {"seletor_item": "li.card",
             "campos": {"titulo": {"seletor": "div.nome", "origem": "texto"},
                        "preco": {"seletor": "span.v", "origem": "texto"}}}
        )}}],
    }
    monkeypatch.setattr(ae.httpx, "post", lambda *a, **k: _RespostaFalsa(corpo))
    return tmp_path / "llm_uso.jsonl"


def test_chamada_do_analista_vai_para_o_log(_llm_falso):
    ae.propor_receita("<ul><li class='card'></li></ul>", [{"nome": "titulo"}], "https://x.com.br/l")
    eventos = custo_llm.ler(_llm_falso)
    assert len(eventos) == 1
    assert eventos[0]["contexto"] == "analista_estrutura"
    assert eventos[0]["url"] == "https://x.com.br/l"
    assert eventos[0]["tokens_entrada"] == 30_000
    assert eventos[0]["custo_usd"] == pytest.approx(30_000 / 1e6 * 0.15 + 500 / 1e6 * 0.60)


HTML = """
<div class="vitrine"><h2 class="head">Cozinha</h2>
  <li class="card"><div class="nome">Sanduicheira</div><span class="v">R$ 99</span></li>
</div>
"""
CAMPOS = [{"nome": "titulo"}, {"nome": "preco"}]
RECEITA_QUEBRADA = {"seletor_item": "li.naoexiste",
                    "campos": {"titulo": {"seletor": "div.nome", "origem": "texto"},
                               "preco": {"seletor": "span.v", "origem": "texto"}}}


def test_reparo_devolve_o_custo_do_ciclo_inteiro(_llm_falso):
    """O custo de um reparo é a soma das tentativas, inclusive as recusadas, que
    custam o mesmo."""
    resultado = supervisor.reparar(HTML, RECEITA_QUEBRADA, CAMPOS, "https://x.com.br/l",
                                   max_tentativas=2)
    assert resultado["custo"]["chamadas"] == 1  # acertou na primeira e parou
    assert resultado["custo"]["tokens_entrada"] == 30_000
    assert resultado["custo"]["custo_usd"] > 0
    assert [c["contexto"] for c in resultado["custo_chamadas"]] == ["supervisor"]


def test_custo_mora_em_um_campo_so_do_artefato(tmp_path, monkeypatch):
    """Fonte única dentro do artefato: o custo fica em `_meta.custo_llm` e o
    `reparo_historico` não guarda uma segunda cópia, pois dois campos com o mesmo
    número podem divergir na primeira edição."""
    monkeypatch.setattr(ae.config, "DIR_RECEITAS", tmp_path)
    receita = {"seletor_item": "li.card", "campos": {}, "_meta": {"dominio": "x.com.br"}}
    reparo = {"tentativas": 2, "pontuacao": 0.9, "historico": [{"pontuacao": 0.4}],
              "validacao_multipagina": {}, "custo": {"chamadas": 2, "custo_usd": 0.01}}
    caminho = ae.salvar_receita(receita, None, reparo=reparo, custo=reparo["custo"])
    gravada = json.loads(open(caminho, encoding="utf-8").read())
    assert gravada["_meta"]["custo_llm"] == {"chamadas": 2, "custo_usd": 0.01}
    assert "custo" not in gravada["_meta"]["reparo_historico"]
    assert gravada["_meta"]["reparo_historico"]["tentativas"] == 2


def test_receita_sem_llm_nao_ganha_campo_de_custo(tmp_path, monkeypatch):
    """Coexistência: receita antiga (e gravação sem custo) segue sem o campo, em vez
    de ganhar um zero que pareceria medição."""
    monkeypatch.setattr(ae.config, "DIR_RECEITAS", tmp_path)
    caminho = ae.salvar_receita({"seletor_item": "li", "_meta": {"dominio": "x.com.br"}})
    gravada = json.loads(open(caminho, encoding="utf-8").read())
    assert "custo_llm" not in gravada["_meta"]
