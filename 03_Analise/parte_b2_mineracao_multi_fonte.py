# -*- coding: utf-8 -*-
"""
TCC Enxame: Parte B2, extensão da amostragem às 3 fontes de Oferta (15/07/2026)

Motivação
---------
A Parte B (10/07, script `parte_b_mineracao_seeds.py`) minerou os termos-semente
dos bestsellers da Shopee, o que era correto na época, porque a Shopee era a única
fonte de Oferta. Desde 13-15/07 o Mercado Livre e a Amazon entraram em produção,
e a camada de Demanda (Google Suggest) ficou observando só o universo da Shopee.

A lacuna, medida: apenas 19% dos bestsellers do ML e 16% dos da Amazon tinham algum
termo-semente que os cobrisse. Categorias inteiras que as fontes novas coletam
(Artigos esportivos, Brinquedos e jogos) não tinham nenhum termo.

Consequência: a H1 continua íntegra (ela cruza Suggest x delta de `sales` da
Shopee; seeds e alvo são ambos Shopee, alinhados por construção), mas o Score fica
sem a dimensão D (demanda) para a maior parte dos produtos de ML e Amazon.

O que o script faz
------------------
Aplica o mesmo método da Parte B (dedupe, normalizar, classificar por regras
documentadas, agregar por termo) sobre as 3 fontes, e emite os termos que ainda
não existem na `tcc_seeds`.

O que não muda:
- O script original fica intacto: o resultado de 10/07 continua reproduzível
  byte a byte. Este aqui importa as 47 regras de lá e apenas as estende.
- O critério de escopo continua o da Parte A: só bens de consumo físicos.
  Produto que não casa com regra nenhuma fica de fora, e isso é o comportamento
  esperado (ver "exclusões que se confirmam", abaixo).

Exclusões que se confirmam sozinhas (achado metodológico)
---------------------------------------------------------
A Amazon traz uma vitrine inteira de Loja Kindle (livros digitais) e o ML traz gift
cards digitais. Ambos caem em Mídia e Software, as duas categorias que a Parte A já
excluiu em 10/07 por serem "bens não físicos, fora do e-commerce físico". Eles saem
como não classificados, como a metodologia prevê. A regra de exclusão se sustentou
contra fontes que não existiam quando ela foi escrita.

Limite do método
----------------
As regras são escritas à mão pelo pesquisador, nas 47 originais e nas novas. A
defesa é a mesma da Parte B: a seleção dos produtos é ditada pelo mercado (são os
campeões de venda reais, não uma escolha nossa); só a nomeação do termo canônico é
regra, e ela fica no script, auditável linha a linha. O que muda é a escala: de 67
para cerca de 257 produtos, a superfície de julgamento cresce.

Entradas (snapshots datados, reproduzíveis):
  - 02_Dados/raw/tcc_bronze_shopee_distinct_2026-07-10.json   (67 produtos)
  - 02_Dados/raw/tcc_bronze_ml_distinct_2026-07-15.json       (154 produtos)
  - 02_Dados/raw/tcc_bronze_amazon_distinct_2026-07-13.json   (36 produtos; o HTML
    e o da fixture de 13/07, pois a Amazon bloqueia a maquina local com 503)

Saídas:
  - 02_Dados/processado/parte_b2_termos_novos.csv        (termos a inserir na tcc_seeds)
  - 02_Dados/processado/parte_b2_classificacao_por_produto.csv  (auditoria linha a linha)
"""
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from parte_b_mineracao_seeds import REGRAS as REGRAS_V1
from parte_b_mineracao_seeds import norm

BASE = Path(__file__).resolve().parent.parent
DATA_INCLUSAO = "2026-07-15"

FONTES = [
    ("shopee", BASE / "02_Dados" / "raw" / "tcc_bronze_shopee_distinct_2026-07-10.json"),
    ("mercado_livre", BASE / "02_Dados" / "raw" / "tcc_bronze_ml_distinct_2026-07-15.json"),
    ("amazon", BASE / "02_Dados" / "raw" / "tcc_bronze_amazon_distinct_2026-07-13.json"),
]
OUT_NOVOS = BASE / "02_Dados" / "processado" / "parte_b2_termos_novos.csv"
OUT_AUDIT = BASE / "02_Dados" / "processado" / "parte_b2_classificacao_por_produto.csv"
SEEDS_V1 = BASE / "02_Dados" / "processado" / "tcc_seeds_candidatos_bestseller_shopee.csv"

# ------------------------------------------------------------------------------
# Regras novas: cobrem os tipos de produto que só aparecem no ML e na Amazon.
# Mesmo formato da v1: (regex, termo canônico, categoria da Google Product Taxonomy).
# Categorias restritas às 16 ativas da Parte A.
# ------------------------------------------------------------------------------
REGRAS_V2 = [
    # --- Eletrônicos: games (console de videogame é "Eletrônicos" na taxonomia do Google) ---
    (r"\bcontrole\b.*\b(ps4|ps5|xbox|playstation|dualsense|dualshock|nintendo|switch)\b|\bjoystick\b|\bcontrole\b.*\bsem fio\b.*\bgamer\b|\bgamesir\b", "controle de videogame", "Eletrônicos"),
    (r"\bconsole\b.*\b(playstation|xbox|nintendo)\b|\bplaystation 5\b.*\bslim\b|\bconsole\b", "console de videogame", "Eletrônicos"),
    # --- Eletrônicos: telefonia e informática ---
    (r"\b(smartphone|celular)\b|\bgalaxy a\d+\b|\bmoto g\d+\b|\biphone \d+\b|\bgalaxy s\d+\b", "smartphone", "Eletrônicos"),
    (r"\bsmart tv\b|\btv \d+ polegadas\b|\btelevis\w+\b", "smart tv", "Eletrônicos"),
    (r"\btv box\b|\broku\b|\bstreaming stick\b|\bchromecast\b|\bfire stick\b", "tv box streaming", "Eletrônicos"),
    (r"\bcart\w+ de mem\w+\b|\bmicro sd\b|\bcartao sd\b", "cartao de memoria", "Eletrônicos"),
    (r"\bcabo hdmi\b|\bhdmi\b", "cabo hdmi", "Eletrônicos"),
    (r"\bpilha\b|\bpilhas\b|\bduracell\b", "pilha alcalina", "Eletrônicos"),
    (r"\bantena\b.*\b(digital|tv)\b", "antena digital para tv", "Eletrônicos"),
    (r"\bcontrole remoto\b.*\btv\b", "controle remoto de tv", "Eletrônicos"),
    (r"\bfilamento\b.*\bpla\b|\bfilamento 3d\b|\bimpressora 3d\b", "filamento para impressora 3d", "Eletrônicos"),
    (r"\bprojetor\b", "projetor", "Eletrônicos"),
    # --- Casa e jardim: eletrodomésticos e utilidades ---
    (r"\baspirador\b|\bextratora\b", "aspirador de po", "Casa e jardim"),
    (r"\baquecedor\b|\btermoventilador\b", "aquecedor eletrico", "Casa e jardim"),
    (r"\bmixer\b", "mixer de cozinha", "Casa e jardim"),
    (r"\bcafeteira\b", "cafeteira", "Casa e jardim"),
    (r"\bbalanca\b.*\b(cozinha|digital|precisao)\b", "balanca digital de cozinha", "Casa e jardim"),
    (r"\bcooktop\b|\bfogao\b", "cooktop eletrico", "Casa e jardim"),
    (r"\btanquinho\b|\blavadora de roupas\b|\bmaquina de lavar\b", "lavadora de roupas", "Casa e jardim"),
    (r"\brefil\b.*\bfiltro\b|\bfiltro\b.*\bpurificador\b|\brefil\b.*\bagua\b", "refil de filtro de agua", "Casa e jardim"),
    (r"\bpapel higienico\b", "papel higienico", "Casa e jardim"),
    (r"\bpercarbonato\b|\btira manchas\b|\balvejante\b", "tira manchas em po", "Casa e jardim"),
    # --- Saúde e beleza ---
    (r"\bsecador\b.*\bcabelos?\b|\bsecador de cabelos\b", "secador de cabelo", "Saúde e beleza"),
    (r"\bcreme\b.*\b(hidratante|corporal|reparador)\b|\bmultirreparador\b|\bhidratante\b", "creme hidratante", "Saúde e beleza"),
    (r"\bprotetor solar\b|\bfps\d+\b", "protetor solar", "Saúde e beleza"),
    (r"\bserum\b|\bvitamina c\b.*\bfacial\b|\bniacinamida\b", "serum facial", "Saúde e beleza"),
    (r"\bshampoo\b|\bcondicionador\b", "shampoo", "Saúde e beleza"),
    (r"\bmaquina de cortar cabelo\b|\baparador de barba\b|\baparador de pelos\b", "maquina de cortar cabelo", "Saúde e beleza"),
    (r"\bmascara\b.*\bcabelos?\b|\bleave[- ]?in\b|\bcapilar\b", "mascara capilar", "Saúde e beleza"),
    (r"\bbody splash\b", "body splash", "Saúde e beleza"),
    (r"\blip ?gloss\b|\bbatom\b|\bgloss labial\b", "gloss labial", "Saúde e beleza"),
    (r"\bwhey\b|\bproteina\b.*\bpo\b|\bcarnibol\b|\bhipercalorico\b", "whey protein", "Saúde e beleza"),
    (r"\bcreatina\b", "creatina", "Saúde e beleza"),
    (r"\bpre ?treino\b|\bpre workout\b", "pre treino", "Saúde e beleza"),
    (r"\bomega ?3\b|\bcapsulas\b", "omega 3", "Saúde e beleza"),
    (r"\bpasta de amendoim\b", "pasta de amendoim", "Alimentos e bebidas"),
    (r"\bsuper coffee\b|\bcafe\b.*\bpo\b", "cafe", "Alimentos e bebidas"),
    (r"\bbarra\b.*\b(proteina|whey)\b", "barra de proteina", "Alimentos e bebidas"),
    # --- Vestuário e acessórios ---
    (r"\bcuecas?\b", "cueca boxer", "Vestuário e acessórios"),
    (r"\bcamiseta\b|\bt[- ]?shirt\b|\bcamisa\b", "camiseta masculina", "Vestuário e acessórios"),
    (r"\bchinelo\b|\bhavaianas\b", "chinelo", "Vestuário e acessórios"),
    (r"\bmeias\b|\bmeia\b.*\bcano\b", "meias", "Vestuário e acessórios"),
    (r"\bcalca jeans\b|\bjeans\b", "calca jeans", "Vestuário e acessórios"),
    (r"\bbermuda\b|\bshorts\b", "bermuda", "Vestuário e acessórios"),
    # --- Malas e bolsas ---
    (r"\bmochila\b", "mochila", "Malas e bolsas"),
    (r"\bmala\b.*\b(bordo|viagem|rodas)\b", "mala de viagem", "Malas e bolsas"),
    # --- Artigos esportivos ---
    (r"\bbola\b.*\b(futsal|futebol|copa)\b|\bbola\b", "bola de futebol", "Artigos esportivos"),
    (r"\bfaixa\w*\b.*\belastic\w*\b|\bmini bands\b|\bthera band\b", "faixa elastica de exercicio", "Artigos esportivos"),
    # --- Brinquedos e jogos ---
    (r"\bmassa\b.*\bmodelar\b", "massa de modelar", "Brinquedos e jogos"),
    # Não usar r"\bjogo\b.*\bpecas\b" aqui. A regra genérica parece boa, mas
    # captura "Jogo 12 Pecas Utensilios Silicone..." (utensílio de cozinha) e casaria
    # também com "jogo de panelas" e "jogo de chaves". Detectado pela checagem de
    # regressão contra os 67 produtos da Shopee em 15/07. Board game só por nome explícito.
    # `norm()` troca hífen por espaço ("Quebra-Cabeca" -> "quebra cabeca"), então a
    # regex precisa aceitar os dois. Detectado pelo teste de regressão em 15/07.
    (r"\buno\b|\bjogo de cartas\b|\bquebra[- ]?cabeca\b|\bcaiu perdeu\b|\bjogo de tabuleiro\b", "jogo de tabuleiro", "Brinquedos e jogos"),
    (r"\bbicicleta\b.*\bequilibrio\b|\btriciclo\b", "bicicleta de equilibrio", "Brinquedos e jogos"),
    (r"\bchocalho\b|\bmordedor\b", "chocalho de bebe", "Infantil"),
    # --- Móveis ---
    (r"\bcadeira\b.*\b(escritorio|gamer|ergonomica)\b", "cadeira de escritorio", "Móveis"),
    (r"\bsuporte\b.*\b(notebook|macbook)\b", "suporte para notebook", "Móveis"),
    (r"\bcolchao\b.*\binflavel\b", "colchao inflavel", "Móveis"),
    # --- Veículos e peças ---
    (r"\bcapacete\b", "capacete de moto", "Veículos e peças"),
    (r"\bmodulo\b.*\b(taramps|amplificador)\b|\bamplificador\b.*\bautomotivo\b", "modulo amplificador automotivo", "Veículos e peças"),
    (r"\bsom automotivo\b|\bradio\b.*\bautomotivo\b", "som automotivo", "Veículos e peças"),
    (r"\bpalheta\b|\blimpador de para ?brisa\b", "palheta limpador de parabrisa", "Veículos e peças"),
    (r"\bcapa\b.*\bchuva\b|\bluva\b.*\bmotoqueiro\b|\bbota\b.*\bgalocha\b", "capa de chuva para moto", "Veículos e peças"),
    # --- Ferragens (ferramentas) ---
    (r"\besmerilhadeira\b|\blixadeira\b.*\bangular\b", "esmerilhadeira", "Ferragens"),
    (r"\bserra\b.*\b(marmore|circular)\b", "serra marmore", "Ferragens"),
    (r"\bpistola\b.*\bpintura\b|\bpulverizador\w*\b", "pistola de pintura", "Ferragens"),
    (r"\b(caixa|maleta)\b.*\bferramenta", "caixa de ferramentas", "Ferragens"),
    (r"\bmini ventilador\b|\bsoprador\b", "soprador de ar portatil", "Ferragens"),
    # --- Materiais de escritório ---
    (r"\bpapel fotografico\b", "papel fotografico", "Materiais de escritório"),
    # --- Ajustes de 15/07, apos conferir a lista de nao-classificados produto a produto.
    # Cada linha aqui nasceu de um bestseller real que ficou orfao, nao de suposicao.
    (r"\bbuds\b|\bairpods\b", "fone de ouvido bluetooth", "Eletrônicos"),
    (r"\bbike ergometrica\b|\bergometrica\b|\bspinning\b", "bicicleta ergometrica", "Artigos esportivos"),
    (r"\bbomba\b.*\b(penalty|bola)\b|\bbomba de encher\b", "bomba de encher bola", "Artigos esportivos"),
    (r"\bcaixa organizadora\b|\borganizador\w*\b.*\bplastic\w*\b", "caixa organizadora", "Casa e jardim"),
    (r"\bcadeira\b", "cadeira", "Móveis"),
    (r"\bfita\b.*\bdupla face\b|\bfita adesiva\b|\bscotch\b", "fita dupla face", "Ferragens"),
    (r"\bwd.?40\b|\bmultiusos?\b.*\baerossol\b|\blubrificante\b", "lubrificante multiuso", "Ferragens"),
    (r"\bcalca\b.*\b(sarja|masculina|social)\b", "calca masculina", "Vestuário e acessórios"),
    (r"\brestaurax\b|\brenova\b.*\bplastico\b|\brenovador\b.*\bplastic\w*\b", "renovador de plastico automotivo", "Veículos e peças"),
]

REGRAS = REGRAS_V1 + REGRAS_V2
REGRAS_COMP = [(re.compile(rx), termo, cat) for rx, termo, cat in REGRAS]


def classificar(titulo_norm: str):
    """Mesma lógica da v1: vence o produto de menor posição no título (o
    'carro-chefe' do bundle); no empate, o padrão mais específico (match mais longo)."""
    melhor = None
    for rx, termo, cat in REGRAS_COMP:
        m = rx.search(titulo_norm)
        if m:
            cand = (m.start(), -(m.end() - m.start()), termo, cat, rx.pattern)
            if melhor is None or cand < melhor:
                melhor = cand
    return (None, None, None) if melhor is None else (melhor[2], melhor[3], melhor[4])


def main():
    termos_existentes = {
        r["termo"] for r in csv.DictReader(SEEDS_V1.open(encoding="utf-8-sig"))
    }

    produtos = []
    for fonte, caminho in FONTES:
        for p in json.loads(caminho.read_text(encoding="utf-8")):
            produtos.append({"fonte": fonte, "product_name": p["product_name"],
                             "item_id": p.get("item_id")})

    agg = defaultdict(lambda: {"categoria": None, "suporte": 0, "fontes": set(), "exemplos": []})
    audit, nao_classificados = [], []
    for p in produtos:
        termo, categoria, _ = classificar(norm(p["product_name"]))
        audit.append({"fonte": p["fonte"], "item_id": p["item_id"],
                      "product_name": p["product_name"],
                      "termo": termo or "", "categoria": categoria or ""})
        if termo is None:
            nao_classificados.append(p)
            continue
        a = agg[termo]
        a["categoria"] = categoria
        a["suporte"] += 1
        a["fontes"].add(p["fonte"])
        if len(a["exemplos"]) < 2:
            a["exemplos"].append(p["product_name"][:60])

    OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with OUT_AUDIT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["fonte", "item_id", "product_name", "termo", "categoria"])
        w.writeheader()
        w.writerows(audit)

    novos = []
    for termo, a in agg.items():
        if termo in termos_existentes:
            continue
        fontes = ",".join(sorted(a["fontes"]))
        novos.append({
            "termo": termo,
            "categoria": a["categoria"],
            "origem": f"bestseller_{fontes}" if len(a["fontes"]) == 1 else "bestseller_multi",
            "justificativa": (
                f"Termo de produto emergente de {a['suporte']} bestseller(s) das fontes [{fontes}] "
                f"(Parte B2, 15/07/2026: extensao da amostragem ao Mercado Livre e Amazon, que "
                f"entraram em producao em 13-15/07). Ex.: {' | '.join(a['exemplos'])}"
            ),
            "ativo": "true",
            "data_inclusao": DATA_INCLUSAO,
            "suporte": a["suporte"],
            "fontes": fontes,
        })
    novos.sort(key=lambda r: (-r["suporte"], r["termo"]))

    with OUT_NOVOS.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["termo", "categoria", "origem", "justificativa",
                                          "ativo", "data_inclusao", "suporte", "fontes"])
        w.writeheader()
        w.writerows(novos)

    # ---- relatório ----
    print(f"Produtos analisados: {len(produtos)} "
          f"(shopee={sum(1 for p in produtos if p['fonte']=='shopee')}, "
          f"ml={sum(1 for p in produtos if p['fonte']=='mercado_livre')}, "
          f"amazon={sum(1 for p in produtos if p['fonte']=='amazon')})")
    cls = len(produtos) - len(nao_classificados)
    print(f"Classificados: {cls}/{len(produtos)} = {100*cls//len(produtos)}%")
    print(f"Termos distintos encontrados: {len(agg)} | JA existentes: {len(agg)-len(novos)} | NOVOS: {len(novos)}")
    print(f"\nTermos NOVOS por categoria:")
    cats = defaultdict(int)
    for r in novos:
        cats[r["categoria"]] += 1
    for c, n in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {n:2d}  {c}")
    print(f"\nTermos NOVOS (por suporte):")
    for r in novos:
        print(f"  {r['termo']:34s} {r['categoria']:24s} sup={r['suporte']:3d}  [{r['fontes']}]")
    print(f"\nNAO classificados: {len(nao_classificados)}")
    for p in nao_classificados:
        print(f"  [{p['fonte']:13s}] {p['product_name'][:66]}")


if __name__ == "__main__":
    main()
