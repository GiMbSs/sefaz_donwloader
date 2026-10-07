---
name: SEFAZ Downloader
description: Estação de trabalho local para operações contábeis de DF-e.
colors:
  navy: "#132841"
  blue: "#1b5a8e"
  canvas: "#f4f1e9"
  surface: "#fffdf8"
  ink: "#14233a"
  line: "#d7d4cb"
  success: "#1b6548"
  warning: "#875e13"
  danger: "#9b3630"
typography:
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  title:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "clamp(1.5rem, 2.4vw, 2.15rem)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.035em"
rounded:
  control: "0.5rem"
  surface: "14px"
spacing:
  control: "0.55rem"
  panel: "1.2rem"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "#ffffff"
    rounded: "{rounded.control}"
    padding: "0.55rem 0.85rem"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0.55rem 0.85rem"
---

# Design System: SEFAZ Downloader

## Overview

**Creative North Star: "A mesa de controle da contabilidade"**

Esta é uma interface de operação, não uma vitrine. A navegação em azul-marinho
mantém a ferramenta ancorada, enquanto a área de trabalho em papel quente dá
prioridade a tabelas, exceções e ações. A densidade é intencional: a pessoa
operadora deve localizar uma empresa, um NSU e uma pendência sem percorrer uma
sequência de cartões decorativos.

**Key Characteristics:**

- Navegação lateral estável e silenciosa.
- Superfícies claras para dados e formulários; cor de destaque apenas em ação e estado.
- Tabelas legíveis, com ações de texto e chaves fiscais em fonte monoespaçada.
- Avisos e bloqueios usam cor sem depender apenas dela.

## Colors

Azul-marinho é a âncora operacional; azul conduz ações e os tons semânticos
explicam disponibilidade, espera e falha.

### Primary

- **Azul de operação:** ação primária, links e foco de trabalho.

### Neutral

- **Marinho de estação:** fundo da navegação e faixa de solicitação.
- **Papel de trabalho:** fundo da área de operação e superfície de dados.
- **Tinta e linha:** texto de alta leitura e separadores discretos.

**The Accent Has a Job Rule.** A cor azul aparece em ação, link e seleção; ela
não é usada para preencher superfícies sem informar uma decisão.

## Typography

**Body Font:** pilha sans do sistema.

**Character:** tipografia nativa e compacta para uso prolongado em planilhas,
tabelas e formulários. Não há fonte de exibição: títulos são definidos pela
escala, peso e espaço, não por ornamentação.

### Hierarchy

- **Title:** usado no título da tarefa atual e com espaçamento negativo discreto.
- **Body:** leitura de contexto, avisos e descrições de operação.
- **Label:** peso alto em campos e cabeçalhos de tabela; cabeçalhos podem usar caixa alta para leitura tabular.

## Layout

A coluna de navegação ocupa 15.5rem em telas amplas. A área de trabalho usa
largura fluida com espaço lateral generoso, painéis de dados em duas colunas e
faixas de estado divididas por linhas. Em até 860px, a navegação se torna uma
barra superior e o conteúdo passa para uma coluna; abaixo de 600px, filtros,
ações e faixas de estado se empilham.

## Elevation & Depth

Superfícies principais usam uma sombra ambiente baixa para se separarem do
papel de trabalho. Linhas e espaçamento ainda fazem a maior parte da divisão;
a sombra não é usada em controles individuais.

## Shapes

Controles recebem curvas discretas e superfícies de dados usam cantos de 14px.
Chips de estado são a única forma inteiramente arredondada, pois comunicam uma
condição curta e não uma ação principal.

## Components

### Buttons

- **Shape:** controles com cantos suaves e altura mínima consistente.
- **Primary:** reservado para salvar ou incluir uma solicitação na fila.
- **Secondary / Quiet:** contexto, edição e cancelamento sem competir com a ação principal.
- **Focus:** contorno âmbar visível e afastado do componente.

### Inputs / Fields

- **Style:** fundo branco, contorno neutro e rótulo acima do campo.
- **Focus:** anel de foco âmbar; erros aparecem com texto e cor vermelha.

### Navigation

- **Style:** trilho marinho, item atual em preenchimento translúcido e rótulo claro.
- **Mobile:** navegação superior compacta sem esconder as rotas essenciais.

### Status

- **Style:** chips curtos com rótulo textual, cores semânticas e contraste alto.
- **State:** verde para disponível/concluído, âmbar para fila/espera e vermelho para falha ou invalidação.

## Do's and Don'ts

### Do:

- **Do** manter dados fiscais em tabelas e blocos de estado, com fontes e ações consistentes.
- **Do** mostrar a origem e a situação de uma solicitação junto do seu contexto de empresa.
- **Do** preservar a ação primária como a decisão principal de cada tela.

### Don't:

- **Don't** transformar a estação em um painel genérico de métricas ou em um navegador de arquivos.
- **Don't** usar cor como única evidência de bloqueio, erro ou disponibilidade.
- **Don't** colocar o NSU em formulários editáveis por pessoas operadoras.
