"""Testes do guardador do registro de chamadas do enxame-api, sem rede.

Cada ramo tem um caso sintético: o log que só cresce passa; a rotação que corta o começo
passa, com as linhas antigas preservadas na cópia; o log reescrito levanta; o container
recriado levanta sem `--container-novo` e registra a lacuna com ele; e linha de requisição
que o padrão não lê levanta em vez de sumir.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import guardar_log_chamadas as g  # noqa: E402

C1 = "2026-08-05T01:39:42.230993185Z"
C2 = "2026-10-02T12:00:00.000000000Z"


def linha(momento: str, status: str = "200 OK", rota: str = "/agentes/coletar") -> str:
    return f'{momento} INFO:     172.18.0.6:57498 - "POST {rota} HTTP/1.1" {status}'


LOG = "\n".join([
    "2026-08-05T01:39:45.272729038Z INFO:     Started server process [1]",
    "2026-08-05T01:39:45.276167794Z INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)",
    linha("2026-08-05T03:00:18.195090785Z"),
    linha("2026-08-05T03:00:22.167218973Z", "503 Service Unavailable"),
    linha("2026-08-05T03:00:25.815108558Z"),
])


def test_extrai_hora_metodo_rota_e_status_e_conta_o_resto():
    chamadas, outras = g.extrair(LOG, C1)
    assert chamadas[1] == (C1, "2026-08-05T03:00:22.167218973Z", "POST", "/agentes/coletar", "503")
    assert len(chamadas) == 3
    assert sum(outras.values()) == 2


def test_linha_de_requisicao_que_o_padrao_nao_le_levanta():
    """Formato novo de log não pode resultar em 'nenhuma chamada nova' com código 0."""
    formato_novo = '2026-10-01T03:00:00.1Z INFO: "POST /agentes/coletar HTTP/1.1" 200'
    with pytest.raises(ValueError, match="padrão não a lê"):
        g.extrair(LOG + "\n" + formato_novo, C1)


def test_primeira_copia_guarda_tudo():
    atuais, _ = g.extrair(LOG, C1)
    linhas, resumo = g.mesclar([], atuais, C1)
    assert linhas == atuais and resumo["novas"] == 3


def test_log_que_so_cresce_acrescenta_so_as_novas():
    guardadas, _ = g.extrair(LOG, C1)
    atuais, _ = g.extrair(LOG + "\n" + linha("2026-08-05T09:00:17.1Z"), C1)
    linhas, resumo = g.mesclar(guardadas, atuais, C1)
    assert resumo["novas"] == 1 and linhas == atuais


def test_log_igual_nao_tem_chamada_nova():
    guardadas, _ = g.extrair(LOG, C1)
    _, resumo = g.mesclar(guardadas, guardadas, C1)
    assert resumo["novas"] == 0


def test_rotacao_que_corta_o_comeco_preserva_o_passado_na_copia():
    """O json-file (3 arquivos de 10 MB) descarta o início; o que saiu do servidor fica na cópia."""
    guardadas, _ = g.extrair(LOG, C1)
    rotacionado = "\n".join([linha("2026-08-05T03:00:25.815108558Z"), linha("2026-08-05T09:00:17.1Z")])
    atuais, _ = g.extrair(rotacionado, C1)
    linhas, resumo = g.mesclar(guardadas, atuais, C1)
    assert resumo["cortadas_pela_rotacao"] == 2 and resumo["novas"] == 1
    assert linhas == guardadas + atuais[1:]


@pytest.mark.parametrize("log_novo", [
    "\n".join([linha("2026-08-05T03:00:18.195090785Z"), linha("2026-08-05T03:00:22.167218973Z", "200 OK")]),
    linha("2026-09-01T03:00:00.1Z"),
], ids=["status_mudou", "comeca_fora_da_copia"])
def test_log_reescrito_levanta(log_novo):
    guardadas, _ = g.extrair(LOG, C1)
    atuais, _ = g.extrair(log_novo, C1)
    with pytest.raises(ValueError, match="só-acréscimo|DIVERGE"):
        g.mesclar(guardadas, atuais, C1)


def test_log_sem_nenhuma_requisicao_levanta():
    guardadas, _ = g.extrair(LOG, C1)
    with pytest.raises(ValueError, match="NENHUMA"):
        g.mesclar(guardadas, [], C1)


def test_container_recriado_levanta_sem_a_decisao():
    guardadas, _ = g.extrair(LOG, C1)
    atuais, _ = g.extrair(linha("2026-10-02T12:05:00.1Z"), C2)
    with pytest.raises(ValueError, match="RECRIADO"):
        g.mesclar(guardadas, atuais, C2)


def test_container_recriado_com_a_decisao_acrescenta_e_declara_a_lacuna():
    guardadas, _ = g.extrair(LOG, C1)
    atuais, _ = g.extrair(linha("2026-10-02T12:05:00.1Z"), C2)
    linhas, resumo = g.mesclar(guardadas, atuais, C2, aceitar_container_novo=True)
    assert linhas == guardadas + atuais
    assert resumo["lacuna_de"] == "2026-08-05T03:00:25.815108558Z" and resumo["lacuna_ate"] == C2


def test_csv_ida_e_volta_preserva_as_linhas():
    guardadas, _ = g.extrair(LOG, C1)
    dado = g.para_csv(guardadas)
    assert b"\r\n" not in dado
    assert g.ler_csv(dado) == guardadas


def test_cabecalho_errado_levanta():
    with pytest.raises(ValueError, match="cabeçalho"):
        g.ler_csv(b"a,b\n1,2\n")
