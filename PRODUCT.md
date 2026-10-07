# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Administradores e operadores de escritórios contábeis que acompanham, configuram
e consultam a distribuição de NF-e e NFC-e de empresas clientes.

## Product Purpose

Executar localmente a recuperação controlada de documentos fiscais eletrônicos
para a contabilidade, mantendo certificados por empresa, histórico auditável,
controle de NSU e uma pasta de XMLs disponível no computador do cliente.

## Positioning

Uma estação de trabalho contábil que trata a consulta à SEFAZ como uma operação
fiscal controlada: o cursor NSU, o certificado, o lote recebido e cada arquivo
extraído são rastreáveis por empresa e ambiente.

## Operating Context

Uso interno em navegador, em instalação Docker local. O escritório cadastra
empresas, configura periodicidade, acompanha solicitações e consulta XMLs já
baixados. A Paraíba é o mercado inicial, com expansão planejada para outras UFs.

## Capabilities and Constraints

- Python 3.13, Django 6, PostgreSQL, Redis e Celery em containers Docker.
- NF-e e NFC-e serão baixadas por empresa, diariamente ou sob solicitação,
  obedecendo o controle de NSU e os intervalos impostos pela SEFAZ.
- Certificados A1/PFX e suas senhas precisam permanecer privados e criptografados.
- XMLs ficam em volume montado fora do container, nunca no media público do Django.
- A interface principal é uma estação de trabalho, não o Django Admin nem um
  navegador genérico de arquivos.

## Evidence on Hand

- PRD: `docs/PRD-IMPLEMENTACAO.md`.
- Não há identidade visual, logotipo ou material de marca fornecido.
- Dados fiscais exibidos durante desenvolvimento devem ser claramente demonstrativos.

## Product Principles

- Segurança fiscal antes de conveniência operacional.
- Uma empresa nunca interfere na operação de outra.
- Estado, espera e falha precisam ser visíveis e explicáveis à contabilidade.
- Ações manuais não podem burlar o cursor ou os limites da SEFAZ.

## Accessibility & Inclusion

Interface em português do Brasil, operável por teclado, com contraste adequado,
estados e mensagens de erro compreensíveis.
