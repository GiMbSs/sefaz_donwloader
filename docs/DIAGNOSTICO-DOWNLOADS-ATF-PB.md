# Diagnóstico de falhas nos downloads

## Falha observada em 20/10/2026

Os logs fornecidos mostram tarefas Celery terminando em cerca de 70 ms com retorno `failed`, sem exceção não tratada. O serviço capturava os erros ATF e retornava o estado do domínio, mas não registrava a causa. Além disso, gravava apenas a categoria `safe_code`, descartando razões como `atf_not_enabled` e `atf_certificate_unavailable`. Alerta e detalhe usavam mensagens genéricas.

O `.env` local não definia `ATF_PB_ENABLED`. Compose e Django usam `False` nesse caso: o worker recusa o acesso antes de contatar a SEFAZ. Esse cenário foi reproduzido em teste e é compatível com o tempo observado. Não foi possível confirmar a causa do pedido histórico: os contêineres da execução relatada não estão disponíveis neste ambiente e a razão específica não era persistida.

A configuração local recebeu `ATF_PB_ENABLED=True`, conforme o uso autorizado dos downloads com A1. As demais configurações e os dados privados foram preservados. Nenhum serviço do cliente foi reiniciado nem pedido remoto foi enviado nesta correção.

## Correções

- Causas conhecidas agora são preservadas no pedido e na tentativa: integração desativada, certificado ausente/vencido, TLS, timeout, conexão, HTTP 429/5xx, mudança de portal e conferência de arquivos.
- O worker registra `event=atf_part_failed`, pedido, parte, tentativa, empresa interna, modelo, formato, etapa, código, classe da exceção, duração, repetição e status HTTP quando disponível. Para falhas inesperadas, registra os nomes de arquivos/funções e linhas da pilha, sem a mensagem bruta da exceção, caminhos privados, respostas, senhas, cookies ou variáveis locais.
- Erros inesperados dentro da etapa recebem diagnóstico persistido e alerta. Uma falha após iniciar envio mantém a barreira e a incerteza; a retomada verifica a caixa e não reenvia o POST.
- Alertas mostram causa e orientação, período/formato/modelo e link para o pedido. O detalhe expõe códigos e tentativas em “Detalhes para suporte”. Partes encerradas com falha não prometem arquivos futuros.
- Erros transitórios mantêm os intervalos e o orçamento de tentativas existentes. Esgotamento em pedidos agendados mantém o reagendamento persistente.

## Aplicar na instalação

Verifique `ATF_PB_ENABLED=True` no `.env` da instalação e atualize os serviços para carregar o código e a configuração:

```bash
docker compose up -d --build --force-recreate web worker scheduler
```

Depois, use **Retomar pedido**. Não é preciso criar outro pedido para o mesmo período. Nos pedidos históricos, o código genérico permanece como foi gravado; a próxima tentativa passa a registrar a causa específica.

Para correlacionar uma falha, procure no log do worker por `event=atf_part_failed` e pelo identificador exibido no pedido. `succeeded: 'failed'` no log do Celery significa que a tarefa executou o tratamento e retornou falha de negócio; não significa que o download foi concluído.

## Verificação

Os testes reproduziram a perda da causa, a ausência de log, as mensagens genéricas e a exceção local sem tratamento antes da correção. Depois da implementação: 161 testes passaram no SQLite (um teste de locks ignorado), 162 no PostgreSQL descartável, Ruff e formatação sem erros, mypy sem problemas em 84 arquivos, Django check sem problemas e migrations sem drift. O teste de falha após envio confirmou que a recuperação baixa o resultado com uma única submissão.

A tela de falha foi inspecionada no Chromium em 1440 px e 390 px, com os detalhes de suporte expandidos: causa, etapa e identificadores visíveis, sem transbordamento da página ou promessa de arquivos em partes encerradas com falha. Capturas sintéticas em `output/playwright/atf-failure-*.png`. Nenhuma nova coleta fiscal real foi executada nesta verificação.

## Retomada e validação do TXT

Os logs posteriores confirmaram execução da etapa às 11:36 e recuperação pelo Beat às 11:39. O Beat consulta os agendamentos e recupera etapas vencidas a cada cinco minutos; `beat: Starting...` é uma confirmação de inicialização. O acompanhamento de uma parte também pode ser entregue diretamente ao worker por ETA, sem uma mensagem correspondente no log do Beat.

O retorno numérico de `schedule_due_downloads` conta pedidos novos das políticas. Ele pode ser zero mesmo quando o worker recebeu partes de pedidos manuais recuperados. Agora `event=atf_scheduler_tick` informa separadamente `created_requests` e `recovered_parts`. Esta última contagem exige publicação aceita pelo broker. `event=atf_part_dispatched` informa parte, tarefa Celery e ETA; falhas de publicação geram `event=atf_dispatch_failed` e alerta de fila.

Um envio incerto sem candidatos fica apresentado como **Aguardando confirmação do envio**, com **Próxima verificação prevista**. O botão de conferência manual aparece quando existem candidatos para revisar; as barreiras e o estado interno de proteção do envio permanecem preservados.

A rejeição posterior ocorreu em `_txt_metadata`. Os dois relatórios de exemplo já disponíveis no projeto usam CNPJ com pontuação; o validador comparava esse texto com o CNPJ canônico do cadastro. Foi corrigido para normalizar a representação antes de comparar. O TXT original permanece intacto. O exemplo NFC-e usa também `AAAA-MM-DD HH:MM:SS`, agora aceito junto de `DD/MM/AAAA`. Datas inválidas ou fora do período continuam rejeitadas.

Os códigos `atf_txt_issuer_mismatch`, `atf_txt_key_issuer_mismatch` e `atf_txt_model_mismatch` distinguem CNPJ do relatório, CNPJ da chave e modelo incorretos. Não foi flexibilizada a correspondência de empresa, chave, número ou modelo. Depois de atualizar a instalação, **Retomar pedido** verifica e baixa novamente o anexo já solicitado, sem enviar outra consulta aceita/incerta.

Os dois TXT de referência passaram pelo leitor após a correção: 23 linhas de NF-e e 7.710 de NFC-e. A revisão equivalente dos XML está documentada em [Validação XML ATF-PB](VALIDACAO-XML-ATF-PB.md).
