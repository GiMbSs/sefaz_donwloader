# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Administradores e operadores de escritórios contábeis que solicitam e acompanham downloads de notas emitidas pelas empresas clientes na SEFAZ-PB.

## Product Purpose

Disponibilizar XML e TXT originais em pastas por CNPJ, formato e data da solicitação, com autenticação A1 individual por empresa, histórico auditável e downloads manuais ou automáticos programáveis.

## Positioning

Uma estação de trabalho contábil para escolher períodos, programar coletas e acompanhar arquivos e falhas. Pedidos, anexos, notas e eventos são rastreáveis por empresa, sem NSU.

## Operating Context

Uso interno em navegador, com instalação Docker local. A SEFAZ-PB pode responder lentamente ou ficar instável; o acompanhamento e a próxima tentativa permanecem visíveis. Pedidos manuais registram o usuário solicitante. Pedidos agendados têm novas tentativas persistidas após esgotar o ciclo curto.

## Capabilities and Constraints

- NF-e modelo 55 e NFC-e modelo 65 como emitente, SEFAZ-PB; XML e TXT chegam em ZIP pela caixa ATF.
- Datas inicial/final obrigatórias em pedidos manuais e períodos completos nas políticas programáveis.
- Modo, frequência, horário, fuso, dias e ativação de agendamento configuráveis.
- Certificados A1/PFX e credenciais recuperáveis cifrados fora do banco e do volume público.
- Pastas privadas em CNPJ-escritório/CNPJ-empresa/NFe|NFCe/XML|TXT/AAAA-MM-DD, com a data original da solicitação.
- Número da nota extraído do XML e conferido com a chave. Notas e eventos separados.
- Nenhum POST de resultado incerto é repetido automaticamente; o sistema concilia a caixa antes de novo envio.
- O histórico do motor nacional anterior não precisa ser preservado. Seus dados e recursos SOAP/NSU foram retirados sem resetar cadastros ou certificados.

## Evidence on Hand

- Plano revisado: `docs/superpowers/plans/2026-10-19-atf-pb-migration.md`.
- Operação: `docs/OPERACAO-ATF-PB.md`.
- Login e ZIP validados anteriormente: `docs/VALIDACAO-AUTENTICACAO-ATF-PB.md` e `docs/VALIDACAO-DOWNLOAD-ATF-PB.md`.
- Dados de demonstração devem ser explicitamente sintéticos.

## Product Principles

- Uma empresa nunca acessa arquivos ou certificados de outro escritório.
- Estado, espera, falha e próxima tentativa são visíveis e compreensíveis.
- Retomadas preservam a identidade do pedido e não criam submissões remotas duplicadas.
- Nenhuma emissão, manifestação, cancelamento ou outra mutação fiscal faz parte do produto.

## Accessibility & Inclusion

Interface em português do Brasil, operável por teclado, com contraste adequado e mensagens de erro compreensíveis.
