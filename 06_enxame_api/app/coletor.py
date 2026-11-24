"""Coleta agendada, de baixo custo e auto-reparável.

Esta é a rota que o n8n chama periodicamente. O princípio que sustenta a tese:
o LLM só é acionado para criar a receita (Agente 2) ou consertá-la (Agente 4);
a coleta de rotina apenas aplica a receita salva, com código determinístico e
custo zero de LLM. Se a receita salva deixar de passar na régua, o reparo é
disparado pelo Agente 4 (Supervisor e Reparador).
"""

import json
from pathlib import Path

from app import bloqueio, coleta_http, coleta_navegador, config, custo_llm
from app.agentes import analista_estrutura, conformidade, supervisor


def carregar_receita_mais_recente(dominio: str) -> dict | None:
    """A receita aprovada mais recente do domínio.

    Receitas reprovadas ficam versionadas em disco como registro auditável (o que
    o LLM propôs e por que foi recusado), mas não entram em produção: só a régua
    determinística decide o que roda. Receitas anteriores a esta marcação
    não têm o campo `aprovada` e são tratadas como válidas.
    """
    pasta = config.DIR_RECEITAS / dominio.replace(":", "_")
    if not pasta.exists():
        return None
    for arquivo in sorted(pasta.glob("receita_*.json"), reverse=True):
        receita = json.loads(arquivo.read_text(encoding="utf-8"))
        if (receita.get("_meta") or {}).get("aprovada") is not False:
            return receita
    return None


def _campos_da_receita(receita: dict) -> list[dict]:
    """Todos os campos que a receita produz, incluindo os de grupo (ex.: categoria),
    que também entram na medição de preenchimento.

    Os nomes saem sempre da receita: é ela quem diz o que produz, e é esse
    conjunto que a régua mede. A descrição é anexada quando o pedido original
    ficou guardado em `_meta.campos_pedidos`; ela não entra na medição, serve ao
    LLM no reparo (o Analista acerta com descrição e erra sem: 0,984 contra 0,167
    no layout de departamento da Amazon, medido em 15/07). Receita sem esse campo
    recebe descrição vazia.
    """
    pedido = {
        c["nome"]: c
        for c in ((receita.get("_meta") or {}).get("campos_pedidos") or [])
        if c.get("nome")
    }
    nomes = list((receita.get("campos_grupo") or {}).keys())
    nomes += list((receita.get("campos") or {}).keys())
    return [
        {
            "nome": nome,
            "descricao": pedido.get(nome, {}).get("descricao", ""),
            "tipo": pedido.get(nome, {}).get("tipo"),
        }
        for nome in nomes
    ]


def coletar(url: str, campos: list[dict] | None, motor: str, user_agent: str) -> dict:
    """Executa uma rodada de coleta. Retorna linhas + diagnóstico.

    Levanta as exceções de coleta (DesafioAntiBot, HTTP) e ValueError quando
    não há receita salva nem `campos` para propor uma nova.
    """
    veredito = conformidade.verificar(url, user_agent)
    if not veredito.permitido:
        raise PermissionError(veredito.motivo)

    # A régua de volume é lida antes da requisição porque o piso de bytes precisa
    # acompanhar o HTML no momento em que ele chega, dentro do `conferir()`. Ler a
    # expectativa é abrir um JSON local: custo zero, sem dependência de rede.
    dominio = analista_estrutura.urlsplit(url).netloc
    volume = bloqueio.volume_esperado(dominio)

    if motor == "navegador":
        html = coleta_navegador.buscar_html_navegador(url)
    else:
        html = coleta_http.buscar_html(url, user_agent, piso_bytes=volume.get("piso_bytes"))

    receita = carregar_receita_mais_recente(dominio)
    llm_usado = False
    reparado = False
    historico_reparo = None
    # Rodada de rotina tem custo zero de LLM, e isso é medido: a soma vai em
    # `custo_llm` na resposta, e o n8n a registra a cada rodada (desde 29/07/2026).
    custo_rodada = custo_llm.somar([])

    if receita is not None:
        campos_efetivos = campos or _campos_da_receita(receita)
        linhas = analista_estrutura.aplicar_receita(html, receita)
        # Régua de volume, aplicada antes da régua de campos (desde 04/08). A ordem
        # importa: uma página com poucos itens tem duas causas possíveis, e só uma é
        # reparável.
        #
        #   página curta demais          -> `conferir()` já abortou acima, pelo piso de bytes
        #   página inteira, poucos itens -> a fonte degradou: nenhum seletor conserta isso
        #   página inteira, itens normais, campos vazios -> a receita: aqui entra o Agente 4
        #
        # Sem esta chamada, o segundo caso cairia no terceiro: a casca do ML (133 KB,
        # título legítimo, nenhum produto) acionaria o reparo e gastaria LLM numa página
        # vazia (medido em 31/07 contra o HTML gravado). E a vitrine `office` da Amazon,
        # com 1 item de 50, seria aprovada pela régua de campos, porque 1 de 1 é 100%.
        bloqueio.conferir_volume(
            url,
            len(linhas),
            volume.get("itens_esperados"),
            volume.get("piso_fracao", 0.5),
        )
        # O gatilho do reparo é a régua, não a contagem de itens. Se só zero itens
        # acionasse o Agente 4, uma receita que casa 50 itens e lê um campo de seis
        # passaria, e a coleta gravaria dados incompletos a cada 6h com
        # `llm_usado: false`. O Supervisor sabe consertar esse caso (o diagnóstico
        # aponta cada seletor errado), desde que seja chamado.
        if not analista_estrutura.aprovada(
            analista_estrutura.validar_receita(linhas, campos_efetivos), receita
        ):
            resultado = supervisor.reparar(html, receita, campos_efetivos, url)
            reparado = True
            llm_usado = True
            historico_reparo = resultado["historico"]
            custo_rodada = resultado.get("custo", custo_rodada)
            if analista_estrutura.aprovada(resultado["validacao"], resultado["receita"]):
                receita = resultado["receita"]
                # `reparo=resultado` grava o histórico do ciclo no próprio artefato
                # (desde 25/07): pontuação antes e depois, tentativas e regressões que
                # barraram uma candidata. É a evidência auditável de que o sistema se
                # reparou sozinho. Ver salvar_receita.
                analista_estrutura.salvar_receita(
                    receita, resultado["validacao"], reparo=resultado, custo=resultado.get("custo")
                )
                linhas = analista_estrutura.aplicar_receita(html, receita)
            else:
                # Falha explícita: erro visível no n8n é melhor que Bronze poluída.
                # A receita reparada e reprovada não é salva aqui; a anterior segue
                # valendo e o próximo ciclo tenta de novo.
                raise RuntimeError(
                    f"Receita de {dominio} não passa na régua e o Agente 4 não conseguiu "
                    f"reparar em {resultado['tentativas']} tentativas "
                    f"(melhor pontuação: {resultado['pontuacao']}). Nada gravado."
                )

    if receita is None:
        if not campos:
            raise ValueError(
                f"Sem receita salva para {dominio} e nenhum campo informado para propor uma nova."
            )
        with custo_llm.sessao() as chamadas:
            receita = analista_estrutura.propor_receita(html, campos, url)
        custo_rodada = custo_llm.somar(chamadas)
        linhas = analista_estrutura.aplicar_receita(html, receita)
        validacao_proposta = analista_estrutura.validar_receita(linhas, campos)
        # A receita é sempre salva, aprovada ou não: o erro do LLM é evidência, e
        # `salvar_receita` marca `_meta.aprovada` para que o carregador não a use.
        analista_estrutura.salvar_receita(receita, validacao_proposta, custo=custo_rodada)
        llm_usado = True
        # A régua vale também para a primeira receita (desde 04/08). Como no caminho
        # do reparo, a proposta reprovada falha explicitamente em vez de devolver
        # linhas, para que uma receita alucinada não chegue à camada imutável. Há um
        # exemplo real no repositório: `lista.mercadolivre.com.br/receita_20260713_204621.json`,
        # com `seletor_item: ".item-class"`. Os 2 domínios em produção já têm
        # receita, então este caminho protege a inclusão de novos domínios.
        if not analista_estrutura.aprovada(validacao_proposta, receita):
            raise RuntimeError(
                f"A receita proposta para {dominio} não passa na régua "
                f"({validacao_proposta['itens_encontrados']} itens). Nada gravado. "
                f"O artefato foi salvo como evidência, marcado `aprovada: false`."
            )

    campos_efetivos = campos or _campos_da_receita(receita)
    validacao = analista_estrutura.validar_receita(linhas, campos_efetivos)

    return {
        "url": url,
        "linhas": linhas,
        "validacao": validacao,
        # O veredito da régua vai na resposta. Sem ele, quem chama (o n8n) recebe
        # linhas sem saber se elas passaram, e a régua fica invisível.
        "aprovada": analista_estrutura.aprovada(validacao, receita),
        "llm_usado": llm_usado,
        "reparado": reparado,
        "historico_reparo": historico_reparo,
        "custo_llm": custo_rodada,
        "crawl_delay": veredito.crawl_delay,
        # O que a fonte pede (`crawl_delay`) costuma ser `None`. Este campo é o
        # número já resolvido, para uso direto por quem chama (ver `coleta_http`,
        # "Quem aplica a pausa").
        "pausa_recomendada_s": coleta_http.pausa_recomendada(veredito.crawl_delay),
        "receita_meta": receita.get("_meta"),
    }
