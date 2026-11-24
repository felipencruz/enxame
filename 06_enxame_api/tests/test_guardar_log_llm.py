"""Testes do guardador do log de custo do LLM, sem rede e com entradas sintéticas.

Cada ramo das duas conferências tem um caso: o log que só cresce passa, o que encolheu
ou foi reescrito levanta, e linha sem custo (modelo fora da tabela de preços) levanta.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import guardar_log_llm as g  # noqa: E402

L1 = json.dumps({"modelo": "gpt-4o-mini-2024-07-18", "custo_usd": 6.6e-06}).encode() + b"\n"
L2 = json.dumps({"modelo": "gpt-4o-mini-2024-07-18", "custo_usd": 0.0065}).encode() + b"\n"


def test_log_que_so_cresce_devolve_as_linhas_novas():
    assert g.conferir_apendice(L1, L1 + L2) == 1


def test_primeira_copia_conta_tudo_como_novo():
    assert g.conferir_apendice(b"", L1 + L2) == 2


def test_log_igual_nao_tem_linha_nova():
    assert g.conferir_apendice(L1 + L2, L1 + L2) == 0


@pytest.mark.parametrize("atual", [L1, L2 + L1, b""], ids=["encolheu", "reescrito", "zerado"])
def test_log_que_nao_e_so_acrescimo_levanta(atual):
    """O caso real que isto previne: container recriado sem o volume ./logs."""
    with pytest.raises(ValueError, match="prefixo"):
        g.conferir_apendice(L1 + L2, atual)


def test_linha_sem_custo_levanta_com_o_motivo_na_mensagem():
    sem_custo = json.dumps({"modelo": "gpt-4o-mini-2099-01-01", "custo_usd": None}).encode() + b"\n"
    with pytest.raises(ValueError, match="tabela de preços"):
        g.conferir_linhas(L1 + sem_custo)


def test_linha_que_nao_e_json_levanta():
    with pytest.raises(ValueError, match="não é JSON"):
        g.conferir_linhas(L1 + b"isto nao e json\n")


def test_linhas_validas_sao_contadas():
    assert g.conferir_linhas(L1 + L2) == 2
