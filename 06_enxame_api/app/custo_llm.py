"""Registro de uso e custo do LLM: quanto custa o enxame se reparar sozinho.

Criado em 29/07/2026. Antes, o `_chamar_llm` lia `choices[0].message.content`
e descartava o bloco `usage` que a própria resposta da OpenAI traz. O trabalho
afirma que a rotina não usa LLM e que ele só entra para criar ou consertar a
receita, e essa afirmação precisa de um número que a sustente. Cada chamada
vira uma linha datada, atribuível ao agente e à página.

O que é medido e o que é derivado:

- Medido: os tokens. Vêm do `usage` da resposta, por chamada. É o dado bruto.
- Derivado: o valor em dólar. Sai da tabela abaixo, que é um retrato datado de
  uma página de preços sujeita a mudança. Por isso o registro guarda os tokens:
  se o preço mudar, o histórico inteiro pode ser reconvertido. Guardar só o USD
  deixaria o valor desatualizado sem nenhum aviso.

O log é append-only, como a Bronze. Linha escrita não se corrige; erro de
registro é declarado na análise.

Falha de gravação não derruba a coleta. É a única exceção deliberada à política
de falha explícita do projeto: perder uma rodada de coleta porque o log de custo
não coube em disco trocaria um problema contábil por uma lacuna na Bronze, que é
imutável. A falha também não é silenciosa: vai para o stderr (visível no log do
container) e incrementa `FALHAS_DE_GRAVACAO`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Tabela de preços: retrato datado, com fonte. Modelo que não estiver aqui grava
# tokens e `custo_usd: null`, com `preco_conhecido: false`. Um custo estimado sem
# base é pior que custo ausente, porque se passa por medição.
# ---------------------------------------------------------------------------
PRECOS_USD_POR_MILHAO = {
    # Standard tier. O `entrada_cacheada` só se aplica ao que a API devolver em
    # `prompt_tokens_details.cached_tokens` (prompt repetido); aqui o HTML muda a
    # cada página, então na prática costuma ser 0, mas o cálculo o considera.
    "gpt-4o-mini": {"entrada": 0.15, "entrada_cacheada": 0.075, "saida": 0.60},
}
PRECOS_FONTE = "https://developers.openai.com/api/docs/pricing"
PRECOS_CONSULTADOS_EM = "2026-07-29"

FALHAS_DE_GRAVACAO = 0

_LOCK = threading.Lock()
_SESSOES: list[list[dict]] = []


def caminho_log() -> Path:
    """Caminho do JSONL. `LLM_LOG_PATH` sobrescreve (a prova controlada usa isso
    para gravar na pasta do experimento sem misturar com o log de produção)."""
    do_ambiente = os.environ.get("LLM_LOG_PATH")
    if do_ambiente:
        return Path(do_ambiente)
    return Path(__file__).resolve().parent.parent / "logs" / "llm_uso.jsonl"


def familia_do_modelo(modelo: str) -> str | None:
    """A entrada da tabela que precifica este modelo, ou None.

    Observado em chamada real (29/07/2026), e não coberto por mock: pedimos
    `gpt-4o-mini` e a API responde `model: "gpt-4o-mini-2024-07-18"`, o snapshot
    datado que de fato atendeu. Com casamento exato, todo evento de produção sairia
    com `custo_usd: null`.

    A regra é casar pelo prefixo mais longo da tabela. Isso é uma inferência
    declarada, não uma medição: assume-se que o snapshot datado tem o preço da
    família listada na página de preços. Por isso o evento guarda os dois nomes:
    `modelo` (o que a API retornou) e `modelo_familia` (o que foi usado no preço).
    Se um snapshot tiver preço próprio, basta incluí-lo na tabela; por ser mais
    longo, ele passa a prevalecer.
    """
    if modelo in PRECOS_USD_POR_MILHAO:
        return modelo
    candidatos = [k for k in PRECOS_USD_POR_MILHAO if modelo.startswith(k)]
    return max(candidatos, key=len) if candidatos else None


def calcular_custo_usd(
    modelo: str,
    tokens_entrada: int,
    tokens_saida: int,
    tokens_cacheados: int = 0,
) -> float | None:
    """USD da chamada, ou None se o modelo não estiver na tabela.

    `prompt_tokens` da OpenAI já inclui os cacheados, que são cobrados mais
    barato; por isso a entrada nova é a diferença, não o total.
    """
    tabela = PRECOS_USD_POR_MILHAO.get(familia_do_modelo(modelo or ""))
    if tabela is None:
        return None
    cacheados = max(int(tokens_cacheados or 0), 0)
    entrada_nova = max(int(tokens_entrada or 0) - cacheados, 0)
    custo = (
        entrada_nova / 1_000_000 * tabela["entrada"]
        + cacheados / 1_000_000 * tabela["entrada_cacheada"]
        + int(tokens_saida or 0) / 1_000_000 * tabela["saida"]
    )
    return round(custo, 8)


def montar_evento(
    *,
    contexto: str,
    modelo: str,
    usage: dict | None,
    duracao_s: float,
    url: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Uma linha do log. `usage` é o bloco cru da resposta, guardado como veio."""
    usage = usage or {}
    entrada = int(usage.get("prompt_tokens") or 0)
    saida = int(usage.get("completion_tokens") or 0)
    cacheados = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    custo = calcular_custo_usd(modelo, entrada, saida, cacheados)
    evento = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "contexto": contexto,  # qual agente gastou: analista_estrutura | supervisor
        "modelo": modelo,  # cru, como a API respondeu (costuma ser o snapshot datado)
        "modelo_familia": familia_do_modelo(modelo or ""),  # o que precificou
        "url": url,
        "tokens_entrada": entrada,
        "tokens_entrada_cacheados": cacheados,
        "tokens_saida": saida,
        "tokens_total": int(usage.get("total_tokens") or (entrada + saida)),
        "custo_usd": custo,
        "preco_conhecido": custo is not None,
        "precos_consultados_em": PRECOS_CONSULTADOS_EM,
        "duracao_s": round(duracao_s, 3),
    }
    if extra:
        evento.update(extra)
    return evento


def registrar(evento: dict, caminho: Path | None = None) -> dict:
    """Grava a linha e devolve o evento. Nunca levanta (ver docstring do módulo)."""
    global FALHAS_DE_GRAVACAO
    with _LOCK:
        for sessao_ativa in _SESSOES:
            sessao_ativa.append(evento)
    destino = caminho or caminho_log()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except OSError as exc:  # noqa: BLE001  # falha aqui não derruba a coleta (ver docstring)
        FALHAS_DE_GRAVACAO += 1
        print(f"[custo_llm] AVISO: log de custo não gravado ({exc})", file=sys.stderr)
    return evento


@contextmanager
def sessao():
    """Acumula os eventos de um ciclo (ex.: um reparo inteiro, com suas tentativas).

    Permite registrar no artefato quanto custou repará-lo. Sem isso, o custo
    ficaria só no log corrido, e a receita, que é a trilha de auditoria, não
    teria o próprio custo.
    """
    eventos: list[dict] = []
    with _LOCK:
        _SESSOES.append(eventos)
    try:
        yield eventos
    finally:
        with _LOCK:
            _SESSOES.remove(eventos)


def somar(eventos: list[dict]) -> dict:
    """Total de uma lista de eventos. `custo_usd` é None se algum evento tiver
    modelo sem preço conhecido, pois um total parcial não pode ser apresentado
    como total."""
    if not eventos:
        return {"chamadas": 0, "tokens_entrada": 0, "tokens_saida": 0,
                "tokens_total": 0, "custo_usd": 0.0, "duracao_s": 0.0}
    tem_desconhecido = any(not e.get("preco_conhecido") for e in eventos)
    return {
        "chamadas": len(eventos),
        "tokens_entrada": sum(e.get("tokens_entrada", 0) for e in eventos),
        "tokens_entrada_cacheados": sum(e.get("tokens_entrada_cacheados", 0) for e in eventos),
        "tokens_saida": sum(e.get("tokens_saida", 0) for e in eventos),
        "tokens_total": sum(e.get("tokens_total", 0) for e in eventos),
        "custo_usd": None if tem_desconhecido else round(
            sum(e.get("custo_usd") or 0.0 for e in eventos), 8
        ),
        "duracao_s": round(sum(e.get("duracao_s", 0.0) for e in eventos), 3),
    }


def ler(caminho: Path | None = None) -> list[dict]:
    """Lê o JSONL inteiro. Linha corrompida é ignorada e contada em `_ilegiveis`
    no resumo; log append-only não é corrigido."""
    destino = caminho or caminho_log()
    if not destino.exists():
        return []
    eventos = []
    for linha in destino.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            eventos.append(json.loads(linha))
        except json.JSONDecodeError:
            eventos.append({"_ilegivel": True})
    return eventos


def resumir(caminho: Path | None = None) -> dict:
    """Painel do log inteiro, com quebra por contexto (quem gastou) e por modelo."""
    eventos = ler(caminho)
    validos = [e for e in eventos if not e.get("_ilegivel")]
    resumo = somar(validos)
    resumo["_ilegiveis"] = len(eventos) - len(validos)
    por_contexto: dict[str, list[dict]] = {}
    por_modelo: dict[str, list[dict]] = {}
    for evento in validos:
        por_contexto.setdefault(evento.get("contexto", "?"), []).append(evento)
        por_modelo.setdefault(evento.get("modelo", "?"), []).append(evento)
    resumo["por_contexto"] = {k: somar(v) for k, v in sorted(por_contexto.items())}
    resumo["por_modelo"] = {k: somar(v) for k, v in sorted(por_modelo.items())}
    return resumo
