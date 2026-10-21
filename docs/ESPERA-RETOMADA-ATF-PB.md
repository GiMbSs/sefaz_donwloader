# Espera pelo ZIP e retomada de pedidos

## Regra de espera

Após terminar o envio à SEFAZ-PB, a primeira consulta à caixa é agendada para pelo menos 60 segundos depois. O intervalo configurado em `ATF_POLL_INTERVAL_SECONDS` é respeitado quando maior. O tempo gasto no envio não consome essa espera.

As verificações seguintes também usam o término da etapa como referência. NFC-e mantém o espaçamento progressivo e a janela prolongada já configurados. A espera é persistida; o worker não fica dormindo.

## Confirmação incerta

`atf_submission_uncertain` registra que a resposta do envio não pôde ser confirmada pelo cliente HTTP. O sistema passa a aguardar e consultar a caixa no mesmo pedido. A ocorrência permanece no histórico da tentativa, sem abrir um alerta de falha apenas por estar nessa situação.

Uma verificação bem-sucedida da caixa limpa o diagnóstico atual de uma falha anterior. Se o arquivo ainda estiver sendo gerado, o pedido continua em espera sem consumir tentativas de erro transitório. Quando o anexo estiver disponível no grupo identificado, ele é baixado e conferido. Notificações antigas de processamento dentro desse grupo não impedem o download de um resultado concluído; grupos candidatos diferentes continuam exigindo conferência.

O reconhecimento da resposta de sucesso no envio não foi ampliado sem evidência do HTML real. Os exemplos de confirmação continuam sendo tratados conservadoramente; a conciliação da caixa resolve os envios incertos.

## Continuidade e retomada

- Uma execução entregue antes do horário se republica para a data prevista, sem acessar a SEFAZ antes dela.
- Uma execução que encontra o acesso da empresa ocupado agenda outra oportunidade, com intervalo mínimo de um minuto.
- O scheduler verifica etapas vencidas a cada minuto e recupera publicações perdidas. Ele respeita os horários persistidos; isso não aumenta a frequência de consultas de NFC-e além da sua política.
- **Retomar pedido** usa o mesmo pedido e período. Após um envio incerto, procura o resultado existente e preserva a espera inicial mínima. Uma etapa que falhou antes de enviar pode voltar à fila.
- As barreiras de envio continuam impedindo a repetição automática de um POST que possa ter sido aceito. Falhas transitórias mantêm as tentativas curtas e os ciclos prolongados dos agendamentos.
- Uma parte na fila verifica as barreiras de envios anteriores antes de reservar o intervalo de leitura da caixa. Assim, a próxima consulta de NF-e ou NFC-e não consome repetidamente a oportunidade necessária para concluir o envio anterior e liberar a fila.

Para atualizar uma instalação existente, reconstruir e reiniciar `web`, `worker` e `scheduler`. Não apagar banco, filas ou pedidos. O scheduler recupera etapas pendentes elegíveis; a retomada pela interface também pode ser usada após a correção.

## Diagnóstico

Os logs passam a registrar adiamento por entrega antecipada/acesso ocupado, próxima verificação persistida e resultado da consulta da caixa, com quantidade de candidatos e anexos. Senhas, certificados, cookies e conteúdo das páginas não são registrados.

Em `atf_part_waiting`, `reason=mailbox_interval` indica espera pelo intervalo da caixa, `account_busy` indica acesso da conta ocupado e `submission_pending` indica outro envio ainda protegido. Neste último caso, `atf_submission_blocked` registra `blocking_request_id`, `blocking_part_id`, `blocking_status`, `blocking_model` e `blocking_code`. Se o bloqueador estiver em falha, revisar ou retomar esse pedido existente; não apagar sua barreira para forçar um novo envio. A repetição de `company_busy` isoladamente só informa disputa pelo acesso da empresa.

Se os containers foram recriados e o driver de logs não reteve os registros, os logs anteriores podem não estar disponíveis. As tentativas persistidas continuam no banco. A mensagem de uma tentativa isolada não permite determinar se houve uma verificação posterior; por isso esta correção foi fundamentada em regressões reproduzíveis do código.

## Verificação

Regressões reproduzidas: envio lento consumia o timer; tarefas antecipadas/acesso ocupado perdiam sua republicação; notificações pendentes bloqueavam um anexo pronto; diagnóstico antigo permanecia durante espera saudável; retomada ignorava a espera inicial. Há um teste do fluxo agendado completo com fila simulada, geração posterior e apenas um envio remoto.

O instante do envio também passa a ser registrado após a preparação do acesso, em vez do início da tarefa; há regressão de preparação lenta para a retomada usar essa referência corretamente.

Também foi reproduzida a disputa em que uma consulta na fila consumia repetidamente o intervalo da caixa antes da consulta pendente. As regressões cobrem NF-e e NFC-e como bloqueador, seguidas do envio e download do próximo pedido, com apenas um envio por parte.

Resultado final: **335 testes passaram** na suíte SQLite; seis testes exclusivos de bloqueios PostgreSQL foram ignorados. Ruff, formatação, mypy e verificações Django aprovados. A correção não exige migration. Revisão independente sem achados bloqueantes. Não foram feitas consultas à SEFAZ nem alterados dados do cliente nesta validação.
