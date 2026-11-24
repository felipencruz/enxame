"""enxame-api: microserviço Python do Enxame (FastAPI).

Hospeda os componentes que não cabem no n8n (container Node, sem Python):
os 4 agentes da extração auto-reparável e, mais adiante, o pipeline
Silver/Gold e os modelos de ML. O n8n chama tudo por HTTP.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import bloqueio, coleta_http, coleta_navegador, coletor, custo_llm
from app.agentes import analista_estrutura, conformidade

VERSAO = "0.1.0"

# Motores de busca de HTML aceitos. A lista existe pelo mesmo motivo do
# `_tipo_conhecido` abaixo: sem ela, `motor` seria string livre e qualquer valor
# diferente de "navegador" cairia no motor http sem aviso ("Navegador", "navegador "
# ou um erro de digitação mudariam o comportamento silenciosamente).
MOTORES = ("http", "navegador")


def _motor_conhecido(v: str) -> str:
    if v not in MOTORES:
        raise ValueError(f"motor {v!r} não existe. Conhecidos: {', '.join(MOTORES)}")
    return v

app = FastAPI(
    title="enxame-api",
    version=VERSAO,
    description=(
        "Microserviço do TCC Enxame — Inteligência de Demanda Multi-marketplace. "
        "Agentes de extração auto-reparável (PoC) + futuro pipeline Silver/Gold e ML."
    ),
)


@app.get("/health")
def health():
    return {"status": "ok", "servico": "enxame-api", "versao": VERSAO}


class PedidoConformidade(BaseModel):
    url: str = Field(..., description="URL que se deseja coletar")
    user_agent: str = Field(
        default=conformidade.USER_AGENT_PADRAO,
        description="User-agent usado na checagem do robots.txt",
    )


@app.post("/agentes/conformidade/verificar")
def verificar_conformidade(pedido: PedidoConformidade):
    veredito = conformidade.verificar(pedido.url, pedido.user_agent)
    return {
        "url": pedido.url,
        "user_agent": pedido.user_agent,
        "permitido": veredito.permitido,
        "motivo": veredito.motivo,
        "robots_url": veredito.robots_url,
        "crawl_delay": veredito.crawl_delay,
        # Número já resolvido para quem chama; o `crawl_delay` cru é quase sempre
        # `None` (ver `coleta_http`, "Quem aplica a pausa").
        "pausa_recomendada_s": coleta_http.pausa_recomendada(veredito.crawl_delay),
    }


class CampoDesejado(BaseModel):
    nome: str = Field(..., description="Nome do campo na receita (ex.: titulo, preco)")
    descricao: str = Field(default="", description="Dica para o LLM do que é o campo")
    tipo: str | None = Field(
        default=None,
        description=(
            "Tipo/faixa que o valor deve respeitar, para a régua do Agente 3: "
            f"{', '.join(sorted(analista_estrutura.VALIDADORES))}. "
            "Sem tipo, o campo é medido só por preenchimento (presença, não validade)."
        ),
    )

    @field_validator("tipo")
    @classmethod
    def _tipo_conhecido(cls, v: str | None) -> str | None:
        """Tipo desconhecido é erro, não é ignorado silenciosamente.

        Sem esta trava, um `"preço"` com cedilha faria `VALIDADORES.get(tipo)`
        devolver None, `taxa_valida` virar `taxa`, e a validação do Agente 3 seria
        desligada sem aviso: o campo seguiria medido só por presença.
        """
        if v is not None and v not in analista_estrutura.VALIDADORES:
            conhecidos = ", ".join(sorted(analista_estrutura.VALIDADORES))
            raise ValueError(f"tipo {v!r} não existe. Conhecidos: {conhecidos}")
        return v


class PedidoReceita(BaseModel):
    url: str = Field(..., description="Página-alvo (passa pelo Agente 1 antes de tudo)")
    campos: list[CampoDesejado] = Field(..., min_length=1)
    user_agent: str = Field(default=conformidade.USER_AGENT_PADRAO)
    motor: str = Field(
        default="http",
        description="Como buscar o HTML: 'http' (leve) ou 'navegador' (Playwright, para sites com JS/anti-bot)",
    )

    @field_validator("motor")
    @classmethod
    def _motor_valido(cls, v: str) -> str:
        return _motor_conhecido(v)


@app.post("/agentes/analista/propor-receita")
def propor_receita(pedido: PedidoReceita):
    """Fluxo completo da PoC: Agente 1 (conformidade), busca do HTML, Agente 2
    (proposta da receita) e aplicação determinística da receita para medir a
    qualidade (régua do Agente 3)."""
    veredito = conformidade.verificar(pedido.url, pedido.user_agent)
    if not veredito.permitido:
        raise HTTPException(status_code=403, detail=f"Agente 1 negou a coleta: {veredito.motivo}")

    try:
        if pedido.motor == "navegador":
            html = coleta_navegador.buscar_html_navegador(pedido.url)
        else:
            html = coleta_http.buscar_html(pedido.url, pedido.user_agent)
    except bloqueio.DesafioAntiBot as desafio:
        raise HTTPException(
            status_code=451,
            detail=(
                f"Coleta abortada por política de ética: {desafio}. "
                "Não resolvemos CAPTCHA; para este alvo, usar o fallback documentado (Apify)."
            ),
        )
    except bloqueio.PaginaBloqueada as bloqueada:
        raise HTTPException(
            status_code=503,
            detail=(
                f"A fonte bloqueou ou não entregou a página: {bloqueada}. "
                "Nada a analisar — o LLM não foi acionado."
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao buscar a página: {exc}")

    campos = [c.model_dump() for c in pedido.campos]
    with custo_llm.sessao() as chamadas:
        receita = analista_estrutura.propor_receita(html, campos, pedido.url)
    custo = custo_llm.somar(chamadas)
    linhas = analista_estrutura.aplicar_receita(html, receita)
    validacao = analista_estrutura.validar_receita(linhas, campos)
    # A receita vai para o disco com o veredito da régua carimbado: se reprovou,
    # fica só como registro auditável e não será carregada em produção.
    arquivo = analista_estrutura.salvar_receita(receita, validacao, custo=custo)

    return {
        "receita": receita,
        "validacao": validacao,
        "aprovada": analista_estrutura.aprovada(validacao, receita),
        "amostra": linhas[:3],
        "arquivo_receita": arquivo,
        "crawl_delay": veredito.crawl_delay,
        "pausa_recomendada_s": coleta_http.pausa_recomendada(veredito.crawl_delay),
        "custo_llm": custo,
    }


class PedidoColeta(BaseModel):
    url: str = Field(..., description="Página-alvo da coleta")
    campos: list[CampoDesejado] = Field(
        default_factory=list,
        description="Só usado se ainda não houver receita salva (para propor a 1ª)",
    )
    motor: str = Field(default="http", description="'http' (padrão) ou 'navegador'")
    user_agent: str = Field(default=conformidade.USER_AGENT_PADRAO)

    @field_validator("motor")
    @classmethod
    def _motor_valido(cls, v: str) -> str:
        return _motor_conhecido(v)


@app.post("/agentes/coletar")
def coletar(pedido: PedidoColeta):
    """Rota de coleta agendada, chamada pelo n8n. Aplica a receita salva sem
    LLM; só aciona o LLM se não houver receita (Agente 2) ou se ela não passar na
    régua (Agente 4)."""
    campos = [c.model_dump() for c in pedido.campos] or None
    try:
        return coletor.coletar(pedido.url, campos, pedido.motor, pedido.user_agent)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"Agente 1 negou a coleta: {exc}")
    except bloqueio.DesafioAntiBot as desafio:
        raise HTTPException(status_code=451, detail=f"Bloqueio anti-bot: {desafio}")
    except bloqueio.PaginaBloqueada as bloqueada:
        raise HTTPException(
            status_code=503,
            detail=(
                f"A fonte bloqueou ou não entregou a página: {bloqueada}. "
                "Coleta abortada sem acionar o LLM (a receita não está quebrada)."
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha na coleta: {exc}")
