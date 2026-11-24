# Enxame

Código da monografia "Extração web auto-reparável orquestrada por um time de agentes de IA para
inteligência de demanda multi-marketplace no e-commerce (Enxame)", do MBA em Big Data, Business
Intelligence e Business Analytics (MB3B) da Escola Politécnica da UFRJ, 2026.

Autor: Felipe Nascimento da Cruz. Orientador: Manoel Villas Bôas Junior.

A monografia está em `Monografia_Enxame.docx`.

## Pastas

- `01_Coleta_n8n/`: os fluxos de coleta do n8n.
- `06_enxame_api/`: o microsserviço dos quatro agentes de extração.
- `03_Analise/`: os scripts da análise.
- `02_Dados/`: os manifestos SHA-256 dos dados e o resultado do experimento 2 da H1.

## O que não está aqui

O dado coletado das lojas (a camada Bronze) e as páginas HTML gravadas nos experimentos não foram
publicados, porque são conteúdo das fontes e seguem os Termos de Uso de cada uma. Eles ficam no
meu repositório privado, e os manifestos SHA-256 em `02_Dados/` servem para conferir qualquer
cópia.

Por isso dá para rodar o código, mas não os passos que leem esse dado. Nos testes dos agentes, 31
dos 200 leem as páginas gravadas e aparecem como pulados; com as páginas presentes, os 200
passaram em 09/11/2026.

## Como rodar

Com Python 3.12, na pasta do projeto:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Testes dos agentes:

```
cd 06_enxame_api
..\.venv\Scripts\python -m pip install -r requirements-dev.txt
..\.venv\Scripts\python -m pytest -q
```

A preparação da Silver precisa da Bronze em `02_Dados/raw/`:

```
.venv\Scripts\python 03_Analise\preparar_silver.py
```

Em 09/11/2026, com o dado presente, ela gerou 103.564 linhas do YouTube, 28.480 da Shopee e
220.945 da Amazon. São esses os números a conferir na tela.
