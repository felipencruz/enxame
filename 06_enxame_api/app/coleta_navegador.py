"""Busca de HTML com navegador real (Playwright + Chromium).

Por que existe: sites como o Mercado Livre servem uma página anti-bot a
clientes HTTP puros (sem JavaScript, sem fingerprint de navegador). Um
navegador de verdade renderiza a página como um usuário comum a vê.

Limites éticos desta camada (capítulo de ética do TCC):
- O Agente 1 (robots.txt) sempre roda antes; URL proibida não chega aqui.
- Não resolve CAPTCHA, não usa login nem cookies, não usa plugin "stealth".
- Volume baixo (coleta agendada, poucas páginas por rodada).
- Se o site barrar um navegador comum, a coleta é abortada e o fato
  documentado; o fallback (Apify) só é acionado por decisão humana.
"""

from app.bloqueio import (  # noqa: F401
    MARCADORES_DESAFIO,
    DesafioAntiBot,
    conferir,
    eh_desafio,
)

TIMEOUT_MS = 60_000
ESPERA_RENDER_MS = 3_000  # folga para conteúdo carregado via JavaScript

# User-agent de um Chrome comum: identidade honesta de navegador, não disfarce.
USER_AGENT_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


def _carregar_playwright():
    """Importa o Playwright só na hora de usar.

    O import no topo obrigaria a biblioteca a estar instalada para o `app`
    subir, já que o `coletor` importa este módulo. Medição de 15/07: a imagem de
    produção carregava 136 MB de Playwright (66% do site-packages) para um motor
    que ela não executa, pois o Chromium não está na imagem. Com o import tardio,
    produção instala só o que usa e o motor 'navegador' segue disponível em
    desenvolvimento (`requirements-dev.txt`).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # ModuleNotFoundError é subclasse
        raise RuntimeError(
            "Motor 'navegador' indisponível: o Playwright não está instalado aqui. "
            "A imagem de produção do enxame-api roda só o motor 'http' — de propósito "
            "(o Chromium também não está nela). Para usar o navegador em "
            "desenvolvimento: pip install -r requirements-dev.txt && playwright install chromium."
        ) from exc
    return sync_playwright


def buscar_html_navegador(url: str) -> str:
    sync_playwright = _carregar_playwright()
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = navegador.new_context(
            locale="pt-BR",
            user_agent=USER_AGENT_NAVEGADOR,
            viewport={"width": 1366, "height": 768},
        )
        pagina = contexto.new_page()
        try:
            pagina.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            try:
                pagina.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass  # networkidle é best-effort; seguimos com o conteúdo disponível
            html = ""
            for _ in range(5):
                pagina.wait_for_timeout(2_000)
                try:
                    html = pagina.content()
                    break
                except Exception:
                    continue  # página ainda navegando (redirect); tenta de novo
            url_final = pagina.url
            # Usa `conferir` completo, como o motor http (`coleta_http.buscar_html`),
            # e não apenas `eh_desafio`. Assim também são barradas a página curta
            # demais e o título de erro, como a página de erro da Amazon documentada
            # em `bloqueio.py` (HTTP 503, 1.643 caracteres, "Algo deu errado"). O laço
            # acima pode terminar com `html = ""` se as 5 tentativas de `content()`
            # falharem; string vazia não casa nenhum marcador e, sem esta checagem,
            # viraria "0 itens" e acionaria o Agente 4 sem necessidade. Não há
            # `status`: o Playwright não expõe o código aqui, e os outros três
            # critérios independem do código HTTP.
            conferir(url_final, html)
            return html
        finally:
            navegador.close()
