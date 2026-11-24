# -*- coding: utf-8 -*-
"""
Inventário das vitrines de mais-vendidos da Amazon e o cruzamento com a Parte A (15/07/2026).

Motivação
---------
A coleta da Amazon usava a página geral de mais-vendidos, e verificou-se que ela
rotaciona as vitrines: 6 por rodada, mas 9 categorias distintas em 4 rodadas, e 3
delas fora do escopo do estudo (Loja Kindle, DVD e Blu-ray, Apps e Jogos =
Mídia/Software, que a Parte A excluiu em 10/07 por não serem bens físicos).

Em 15/07 optou-se por trocar a página geral por vitrines fixas por departamento.
Este script materializa a escolha sem julgamento do pesquisador: entra todo
departamento que a Amazon publica e que cai dentro do escopo já declarado na Parte A;
ficam de fora os que a Parte A já excluía antes de a Amazon entrar no projeto.

Origem do inventário
--------------------
A fixture `amazon_bestsellers_20260713.html` (HTML real servido ao VPS em 13/07), da
qual foram extraídos os links da navegação de departamentos. Custo: nenhuma
requisição à Amazon.

Essa fixture não está mais no repositório: foi apagada em 17/07 junto com
`test_receita_amazon.py`, que testavam a rota geral aposentada em 15/07, e a pasta
`06_enxame_api/tests/fixtures/` não existe hoje. A procedência do inventário continua
sendo a descrita acima. Pendência registrada no README do enxame-api: a rota atual da
Amazon não tem fixture nem teste local; ela roda em produção, coberta pela régua em
runtime. Com as 14 receitas versionadas, a fixture pode ser gerada a partir delas.

O que foi medido
----------------
- O Agente 1 (portão de robots.txt) permite `/gp/bestsellers/` e as rotas por
  departamento para o `EnxameBot`, verificado no próprio agente e não pela leitura
  manual do robots.
- A página de departamento entrega 50 produtos com rank contínuo #1..#50 (contra
  6 por vitrine, com rank que reinicia) e, ao contrário da página geral, entrega
  o preço ao `EnxameBot` (50/50 em toys; 42/50 em sports), medido em 15/07.

Uso: python 03_Analise/amazon_vitrines_inventario.py
"""

BASE = "https://www.amazon.com.br/gp/bestsellers/"

# slug -> (rótulo que a Amazon exibe, categoria da Parte A ou None se fora de escopo,
#          justificativa quando fora)
VITRINES = {
    # --- Em escopo (22) -----------------------------------------------------
    "amazon-devices":      ("Dispositivos Amazon e Acessórios", "Eletrônicos", None),
    "appliances":          ("Eletrodomésticos", "Casa e jardim", None),
    "automotive":          ("Automotivo", "Veículos e peças", None),
    "baby-products":       ("Bebês", "Infantil", None),
    "beauty":              ("Beleza", "Saúde e beleza", None),
    "computers":           ("Computadores e Informática", "Eletrônicos", None),
    "electronics":         ("Eletrônicos", "Eletrônicos", None),
    "fashion":             ("Moda", "Vestuário e acessórios", None),
    "furniture":           ("Móveis", "Móveis", None),
    "grocery":             ("Alimentos e Bebidas", "Alimentos e bebidas", None),
    "hi":                  ("Ferramentas e Materiais de Construção", "Ferragens", None),
    "home":                ("Casa", "Casa e jardim", None),
    "hpc":                 ("Saúde e Bem-Estar", "Saúde e beleza", None),
    "kitchen":             ("Cozinha", "Casa e jardim", None),
    "lawn-and-garden":     ("Jardim e Piscina", "Casa e jardim", None),
    "musical-instruments": ("Instrumentos Musicais", "Artes e entretenimento", None),
    "office":              ("Papelaria e Escritório", "Materiais de escritório", None),
    "pet-products":        ("Pet Shop", "Animais e pet", None),
    "premium-beauty":      ("Beleza Premium", "Saúde e beleza", None),
    "sports":              ("Esporte", "Artigos esportivos", None),
    "toys":                ("Brinquedos e Jogos", "Brinquedos e jogos", None),
    "videogames":          ("Games e Consoles", "Eletrônicos", None),
    # --- Fora do escopo (6): pela mesma regra da Parte A, escrita em 10/07 ---
    "books":        ("Livros", None, "Mídia: bem de conteúdo, não físico (Parte A, 10/07)"),
    "digital-text": ("Loja Kindle", None, "Mídia: livro digital, não é bem físico (Parte A, 10/07)"),
    "dvd":          ("DVD e Blu-ray", None, "Mídia: bem de conteúdo (Parte A, 10/07)"),
    "music":        ("CD e Vinil", None, "Mídia: bem de conteúdo (Parte A, 10/07)"),
    "mobile-apps":  ("Apps e Jogos", None, "Software: produto não físico (Parte A, 10/07)"),
    "gift-cards":   ("Gift Cards", None, "Não é bem de consumo físico; foi também o único "
                                         "resíduo não classificado da Parte B2 (Parte A, 10/07)"),
}

# Categorias ativas da Parte A (16), para medir a cobertura, não para escolher.
PARTE_A_ATIVAS = [
    "Eletrônicos", "Saúde e beleza", "Vestuário e acessórios", "Casa e jardim",
    "Móveis", "Artigos esportivos", "Animais e pet", "Brinquedos e jogos",
    "Infantil", "Câmeras e óptica", "Ferragens", "Materiais de escritório",
    "Malas e bolsas", "Veículos e peças", "Alimentos e bebidas",
    "Artes e entretenimento",
]


def em_escopo():
    return {s: v for s, v in VITRINES.items() if v[1] is not None}


def url(slug: str) -> str:
    return f"{BASE}{slug}/"


def main():
    dentro, fora = em_escopo(), {s: v for s, v in VITRINES.items() if v[1] is None}
    print(f"Vitrines publicadas pela Amazon: {len(VITRINES)}")
    print(f"  em escopo:      {len(dentro)}")
    print(f"  fora de escopo: {len(fora)}\n")

    print("FORA DE ESCOPO (a regra e a mesma de 10/07 — nao foi escrita para a Amazon):")
    for slug, (rot, _, motivo) in sorted(fora.items()):
        print(f"  {rot:38s} {motivo}")

    cobertas = {v[1] for v in dentro.values()}
    print(f"\nCategorias da Parte A cobertas: {len(cobertas)} de {len(PARTE_A_ATIVAS)}")
    for c in PARTE_A_ATIVAS:
        vitrines = sorted(rot for rot, cat, _ in dentro.values() if cat == c)
        marca = "  " if vitrines else "->"
        print(f" {marca} {c:26s} {', '.join(vitrines) if vitrines else 'SEM VITRINE EQUIVALENTE'}")

    print("\nAs 2 sem vitrine equivalente nao sao omissao: a Amazon nao publica")
    print("departamento de mais-vendidos para elas — dilui Cameras em `electronics`")
    print("e Malas e bolsas em `fashion`. Fica declarado como limitacao da fonte.")

    # A Amazon coleta a 12/12h (2 rodadas/dia). Medido no painel [util] Status das
    # Coletas (execucao 2844, 31/07/2026): 1.100 linhas por snapshot (22 vitrines x 50)
    # e 2 snapshots/dia = 2.200 linhas/dia. O limiar de 18h do alerta de coletor
    # parado existe porque Amazon e YouTube sao 12/12h.
    print(f"\nVolume estimado: {len(dentro)} vitrines x 50 produtos = {len(dentro)*50} linhas/rodada")
    print(f"                 a 12/12h (2 rodadas/dia) = {len(dentro)*50*2} linhas/dia")

    print("\nURLs (todas verificadas como permitidas pelo Agente 1 em 15/07):")
    for slug in sorted(dentro):
        print(f"  {url(slug)}")


if __name__ == "__main__":
    main()
