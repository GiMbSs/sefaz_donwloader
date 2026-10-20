# Migração para downloads de NF-e no ATF da SEFAZ-PB

## Objetivo e evidência

Atender à contabilidade com downloads de notas emitidas pela empresa, em XML e TXT, usando o certificado A1 individual da empresa no portal ATF da SEFAZ-PB. Substituir a distribuição nacional DF-e e eliminar o controle de NSU deste produto.

O fluxo foi validado em produção com um A1 e um período: autenticação por certificado TLS, consulta de emitente por CNPJ, solicitação assíncrona, caixa de mensagens e download de ZIP. Os resultados e endpoints estão em [VALIDACAO-DOWNLOAD-ATF-PB.md](../../VALIDACAO-DOWNLOAD-ATF-PB.md) e [VALIDACAO-AUTENTICACAO-ATF-PB.md](../../VALIDACAO-AUTENTICACAO-ATF-PB.md). O ZIP XML continha 16 NF-e e 9 eventos; o ZIP TXT continha um relatório Windows-1252 com as mesmas 16 chaves. Um experimento não garante estabilidade dos endpoints nem todas as condições de operação.

## Escopo e decisões propostas

Decisões já informadas pelo cliente: SEFAZ-PB, A1 por empresa, notas emitidas, XML e TXT, entrega por ZIP, ausência de NSU e manutenção do mecanismo de download automático programável, adaptado ao novo fluxo.

As escolhas abaixo são propostas técnicas deste desenho, não decisões previamente aprovadas pelo cliente:

- Evoluir o repositório existente. Preservar Django, Celery, Redis, PostgreSQL, contas, escritórios, permissões, cadastros, cofre e infraestrutura de armazenamento. Evitar um reinício que perderia recursos já úteis.
- Nesta entrega, consultar NF-e modelo 55 como emitente. Destinatários, CT-e e NFC-e não entram automaticamente no escopo por existirem no portal ou em exemplos anteriores.
- Manter o mecanismo de download automático programável, incluindo modos manual, automático e híbrido, frequências diária, semanal e mensal, horário, fuso, dias configurados e ativação. Adaptar a coleta para consultas de período e formato. Políticas existentes mantêm seu modo e estado ativo/inativo; o default manual e sem agendamento vale apenas para cadastros novos.
- No formulário manual, exigir datas explícitas e permitir XML, TXT ou ambos; selecionar ambos por padrão. Um resultado histórico não impede uma nova coleta explícita do mesmo período, necessária para capturar eventos posteriores.
- Dividir períodos extensos em partes por mês civil e formato. Cada parte fica em um único ano e nunca ultrapassa o limite de um ano observado na interface. Não presumir que consultas vazias são erros.
- Manter o cadastro de UF da empresa, mas retirar o seletor de produção/homologação da operação nova. A origem é o portal real ATF-PB; não há endpoint de homologação validado para este fluxo. Documentos legados mantêm a origem e o ambiente históricos, sem reclassificação.
- Preservar os ZIPs originais como entrega principal, com índice de notas e eventos para consulta. Não converter o TXT a partir dos XMLs: o TXT vem da SEFAZ.
- Preferir HTTP direto. Automação de navegador não é dependência inicial; mudanças de autenticação do portal devem produzir erro explícito, sem contornar desafios de acesso.

## Experiência e operação

O operador abre uma empresa, informa o período e os formatos e solicita os arquivos. A interface mostra o pedido, suas partes, o processamento e os ZIPs disponíveis. O download original e os erros ficam vinculados à empresa. O operador pode repetir um período concluído ou retomar uma coleta interrompida; repetir não deve ocorrer silenciosamente como consequência de um timeout.

O painel substitui contadores de NSU por solicitações na fila, em processamento, aguardando ATF, com resultado vazio, com falha ou concluídas. Os detalhes mostram datas, formatos, partes, horários e resultados. A lista de documentos diferencia notas de eventos e apresenta os relatórios TXT por pedido, sem sugerir que 25 XMLs significam 25 notas.

Somente membros autorizados do escritório acessam pedidos, ZIPs, documentos, eventos, relatórios e histórico legado. Alterar uma URL ou usar o admin não pode atravessar escritórios. O web continua sem chave privada do cofre e com armazenamento fiscal somente para leitura; somente o worker descriptografa A1, acessa o ATF e escreve os arquivos. Não expor caixa de mensagens genérica ao usuário nem abrir avisos não relacionados às consultas NF-e.

Rotinas agendadas produzem os mesmos pedidos e partes que a operação manual. O agendamento existente é preservado, inclusive frequência, horário, fuso, dias da semana/dia do mês, modo e estado ativo/inativo. Estratégias propostas para adaptar o período: `previous_day`, `previous_month` e `rolling_days`; o mapeamento inicial é diária/dia anterior, semanal/últimos sete dias completos e mensal/mês anterior completo, com XML e TXT por padrão e possibilidade de edição. Períodos terminam ontem no fuso IANA já configurado na política; `America/Fortaleza` é somente o default de políticas novas. A ativação de um agendamento existente não depende de recadastro nem de reativação manual após a migração. O histórico de execução substitui qualquer cursor; dias sem execução são recuperados por janelas explícitas, não por NSU. A pausa global necessária ao corte é temporária e não modifica a configuração ativa/inativa de cada política. Após o corte, retomar os agendamentos que estavam ativos, sem duplicar a mesma ocorrência e sem interpretar uma execução antiga de NSU como cobertura de um período ATF.

## Domínio novo

Manter o app `fiscal`, criando modelos com nomes do fluxo novo em vez de reutilizar estados SOAP com outro significado:

| Entidade | Responsabilidade |
| --- | --- |
| `DownloadPolicy` | Modo, frequência, horário, fuso, dias de semana/dia do mês, estratégia de período, quantidade de dias, formatos, ativação e resultados recentes |
| `DownloadRequest` | Empresa, período original, formatos, origem manual/agendada, solicitante, política, status, correlação e eventual pedido anterior repetido |
| `DownloadPart` | Um mês e formato, estado persistido, tentativa, evidência anterior ao envio, IDs remotos descobertos, próxima verificação e resultado |
| `DownloadAttempt` | Operação, início/fim, resultado, erro classificado e certeza sobre envio remoto, sem corpo HTML, segredo ou cookie |
| `DownloadArchive` | ZIP original, parte, mensagem e índice do anexo, nome de apresentação, tamanho, checksum e caminho privado |
| `ArchiveMember` | Nome do membro no ZIP, tipo, checksum, caminho privado se materializado e associação ao XML de nota/evento ou relatório |
| `InvoiceDocument` | NF-e lógica, única por empresa e chave, modelo e dados mínimos de consulta |
| `InvoiceXmlVersion` | Versões de XML da nota, únicas por nota e checksum; nunca sobrescrever uma versão anterior |
| `FiscalEvent` | Chave da NF-e, tipo, sequência, checksum, XML e status de validação; autoria de um evento pode ser do destinatário |
| `LegacyFiscalRecord` | Snapshot imutável dos registros antigos, IDs, relações, ambiente original e referências aos arquivos preservados |
| `LegacyMigrationRun` | Manifesto verificado, contagens e fingerprints dos snapshots e arquivos para autorizar a retirada das tabelas antigas |
| `AtfAccessLease` | Exclusão distribuída temporária da conta remota/caixa e da etapa de acesso em andamento |
| `RemoteSubmissionBarrier` | Barreira persistente por CNPJ/conta enquanto uma submissão não foi conciliada; não expira junto com o lease |
| `RemoteResultBinding` | Associação exclusiva de grupo remoto à parte, incluindo conta remota, dados de conferência e eventual resolução auditada |

`DownloadRequest` tem estados `queued`, `running`, `waiting`, `succeeded`, `partial`, `empty`, `failed` e `cancelled`. `DownloadPart` tem estados `queued`, `submitting`, `waiting`, `ambiguous`, `downloading`, `validating`, `succeeded`, `empty` e `failed`. `ambiguous` exige conciliação; não reenvia automaticamente a consulta. O pedido fica `waiting` enquanto há partes ambíguas e `partial` quando termina com algumas partes entregues e outras com falha. `succeeded` exige que todas as partes tenham terminado com arquivos válidos ou vazias, com pelo menos um arquivo. Todas vazias resulta em `empty`. Cancelamento local interrompe novas etapas, mas não promete cancelar um processamento já enviado ao ATF.

Formatos são valores canônicos `xml` e `txt`, ordenados no cálculo de uma chave de idempotência ativa. A exclusividade ativa impede duplicar o mesmo pedido da mesma empresa, período e conjunto de formatos por clique duplo ou redelivery. Partes são únicas por pedido, início, fim e formato. Um pedido concluído pode ser repetido explicitamente, registrando `repeat_of`.

Notas têm identidade por chave; eventos não competem com a nota pela mesma restrição de unicidade. Um evento é deduplicado por empresa, chave, tipo, sequência e checksum. Resultados parciais e arquivos originais permanecem disponíveis. A revalidação local reutiliza o ZIP armazenado e não faz outra solicitação remota.

## Contrato de integração

Implementar cliente dedicado `AtfPbClient`. O cliente recebe uma sessão TLS autenticada em contexto de curta duração e expõe operações de autenticação, consulta do emitente, submissão, listagem paginada de mensagens, abertura de filhas e download de anexo. O contrato detalhado de campos/endpoints segue o relatório de validação; nunca fixar os dados da empresa usada no experimento.

Extrair campos ocultos e atribuições conhecidas do componente de pesquisa como dados, usando parser de HTML e gramática restrita para literais. Não usar `eval`, motor JavaScript ou execução de código recebido do portal. A consulta de CNPJ precisa devolver exatamente a empresa do pedido.

Usar `requests.Session`, contexto TLS próprio, cadeia de confiança e timeouts. Na autenticação e nos redirects, permitir apenas HTTPS e hosts SEFAZ explicitamente configurados; nunca encaminhar A1 ou cookies para outro domínio. O web não recebe material descriptografado. Em Linux, preferir descritor de memória para PEM. Em Windows nativo, se necessário, usar PEM privado criptografado com senha aleatória apenas em diretório temporário privado cuja ACL seja verificada; limpar em `finally` e recusar um fallback sem proteção verificável. Preservar o funcionamento de Docker/Linux e do desenvolvimento Windows, com teste de cada backend suportado.

Antes de cada envio, persistir baseline paginado dos grupos NF-e visíveis, filtros, formato, instante e tentativa. Persistir `submitting` antes da chamada remota. A resposta de sucesso indica enfileiramento, não download pronto. IDs de grupo, mensagem e anexo pertencem ao ATF e substituem a correlação operacional que antes estava ligada aos lotes SOAP.

Para correlacionar, combinar diferença de IDs, remetente/função NF-e, dados do pedido, período confirmado na mensagem e formato real do arquivo. Não selecionar só a data mais recente ou exigir exatamente três mensagens. Paginar a caixa e tratar vários anexos. Timestamps do portal não são prova única de autoria, nem devem ser tratados como UTC sem evidência. Se mais de um candidato continuar indistinguível, marcar `ambiguous` e apresentar somente candidatos de consultas NF-e para revisão operacional autorizada.

Persistir a associação em `RemoteResultBinding`, com unicidade de `(remote_account_key, parent_message_id)`, e proibir que o mesmo anexo seja registrado para partes diferentes por `(remote_account_key, message_id, attachment_index)`. Somente administrador do escritório pode confirmar um candidato ambíguo por ação auditada. A confirmação exige remetente/função, período e filtros compatíveis; o arquivo é baixado primeiro para staging/quarentena e o formato e a empresa são verificados antes de liberá-lo. Uma associação já usada em outro escritório produz indisponibilidade genérica, sem expor dados desse escritório. A associação sobrevive a retomadas e revalidações.

Timeout, encerramento do worker ou erro de parsing depois de um POST não provam que o pedido deixou de ser criado. Recuperar por conciliação da caixa. Não repetir automaticamente POST de submissão nem fazer logout genérico que possa encerrar uma sessão usada por outra operação. A leitura de mensagens dos pedidos pode marcá-las como lidas; não executar `darCiencia`, exclusão ou ocultação de mensagens.

Pedidos acima de um ano serão particionados em meses, sem dependência de um único resultado anual. XML e TXT de uma mesma parte temporal são solicitações distintas. O processamento deve preservar qualquer resultado de mês já concluído quando outro falhar.

## Assincronia, concorrência e recuperação

Cada tarefa Celery executa uma etapa curta e persiste o resultado. A espera é feita por próxima tarefa com ETA, sem `sleep` no worker. Usar atualização de caixa no máximo uma vez a cada 60 segundos por conta remota. Proposta inicial: prazo de espera de 24 horas, renovável por retomada explícita e limitado por métricas; esse prazo é decisão operacional, não limite anunciado pelo ATF.

Cookies ficam em memória e não entram em banco, Redis, resultados Celery ou logs. Uma tarefa futura pode autenticar novamente e continuar pelos IDs persistidos. O processo de download abre a mensagem correta imediatamente antes de cada anexo, na mesma sessão. Essa sequência é indivisível sob o lease; `hidAnexo=0` não identifica um arquivo globalmente.

Exclusão por empresa/CNPJ protege submissões do mesmo contribuinte inclusive em escritórios diferentes. Após autenticar, uma segunda chave de lease derivada por hash do identificador da conta remota protege a caixa quando certificados de empresas distintas acessam a mesma conta. Não persistir esse identificador em texto aberto. Antes de conhecer a conta, autenticação não lê nem modifica a caixa; depois de conhecê-la, respeitar o lease e o intervalo já registrados para ela. Empregar tokens de fencing, expiração e heartbeat. Não manter transação ou row lock durante tráfego HTTP; uma tarefa antiga que perdeu o lease não pode gravar conclusão nem iniciar outra submissão.

O lease sozinho não impede que um POST já em trânsito produza resultado depois de sua expiração. Antes de enviar, gravar `RemoteSubmissionBarrier` para o CNPJ e a conta, vinculada à parte e tentativa. A barreira não tem expiração automática e bloqueia novas submissões conflitantes até a associação remota ser conciliada. Um worker substituto pode reconciliar e baixar, mas não enviar outro POST enquanto a barreira anterior estiver pendente. Se não for possível comprovar o resultado, um administrador poderá encerrar localmente a tentativa incerta com justificativa, reconhecendo que o pedido remoto pode existir; a ação é auditada, não envia novo pedido e não equivale a prova de ausência no ATF.

Retries automáticos limitados a operações idempotentes e a falhas transitórias: até três tentativas, atrasos mínimos de 60, 120 e 240 segundos, respeitando `Retry-After` se maior. Submissão incerta, empresa divergente, A1 inválido e mudança de HTML não são tratados como falha transitória genérica. Falha parcial não descarta ZIP pronto. Retomada continua a etapa persistida e não zera o pedido.

## Armazenamento e validação

Manter raiz externa configurada por `NOTES_STORAGE_ROOT` e caminhos privados relativos ao escritório/empresa. Novo layout proposto: `escritorios/<escritorio>/empresa_<cnpj>/atf-pb/pedidos/<uuid>/partes/<uuid>/...`, com nomes internos gerados pelo servidor. Guardar nome remoto apenas como metadado saneado. Arquivos antigos ficam nos caminhos atuais e continuam acessíveis pelo adaptador legado.

Download em streaming com teto de bytes, hash incremental, staging privado e publicação por rename atômico. Limites iniciais configuráveis: ZIP de 200 MiB, descompactação acumulada de 1 GiB, 50.000 entradas, XML de 10 MiB e TXT de 100 MiB por entrada. Os limites são guardas técnicos propostos; o ZIP real pequeno não comprova comportamento em cargas máximas. Não confiar em `Content-Length`, extensão ou `Content-Type` isolados. Rejeitar HTML de login recebido como arquivo, ZIP inválido, arquivo truncado, path traversal, nomes absolutos, links simbólicos e nomes normalizados duplicados.

Nunca extrair ZIP arbitrariamente no filesystem. Validar CRC com leitura limitada pelo orçamento real descompactado. Decodificar XML sem DTD, entidades externas ou rede. Validar modelo 55, chave, emitente e `tpAmb=1` das notas novas; eventos são validados por chave associada, tipo e sequência, sem exigir que o autor seja a empresa emitente. Datas de eventos podem ser posteriores às datas da nota. A validação de período usa a emissão da nota, não a data do evento.

Reutilizar schemas NF-e/eventos disponíveis quando aplicáveis. Retirar schemas exclusivos do transporte de distribuição. XML estruturalmente válido cujo XSD não está disponível fica `pending_schema`, com alerta, sem impedir a entrega do ZIP íntegro. Não anunciar validação de assinatura criptográfica apenas por XML/XSD válidos. Conteúdo malformado ou de outra empresa não deve ser liberado como resultado validado; preservar a evidência em quarentena privada, registrar falha e permitir retomada local após correção.

Preservar o TXT original. Reconhecer BOM/UTF-8 válido e Windows-1252 sem substituição silenciosa de caracteres; identificar relatório vazio e limites sem exigir layout analítico ainda não contratado. Comparar chaves com XML quando os dois formatos tiverem sido solicitados, como diagnóstico de divergência; TXT sozinho não depende de ter XML disponível. Não implementar importador manual de TXT ou reconstrução de relatório fiscal nesta migração.

## O que sai e o que permanece

Remover do runtime: `NsuControl`, cursor e correção inicial/manual/automática de NSU, bloqueios por NSU e códigos 137/138/656, cliente nacional SOAP/`distNSU`, `docZip`/base64/gzip, `DistributionBatch`/`DistributionItem`, reprocessamento de lote SOAP, estados e alertas exclusivos desse protocolo e configuração de seus ambientes/endpoints. `SyncPolicy`, `SyncRequest` e `FiscalDocument` antigos são substituídos pelo domínio acima depois de arquivados.

Preservar e adaptar: controle de acesso, ciclo de vida da empresa, cadastro de escritórios, upload e cofre A1, storage privado, recorrência, auditoria e alertas, healthcheck, telas e infraestrutura. Autenticação, validade, erro TLS, fila e falha de arquivo continuam sendo conceitos úteis; não apagar genericamente alertas de segurança ou recuperação por terem sido usados no fluxo antigo.

Deixar fora do runtime e marcar como superados: o plano de importação manual TXT, a premissa de homologação da distribuição nacional e exemplos/documentação de comandos antigos. Não apagar evidências da validação nova. Remover ativos XSD somente após separar os schemas NF-e/eventos que ainda são necessários.

## Migração e proteção de dados existentes

Não resetar banco, reescrever migrations aplicadas ou apagar arquivos de clientes. Preservar migrations históricas e qualquer função importada por elas até garantir migração de um banco vazio.

1. Suspender agendamento antigo e impedir novas chamadas ao cliente nacional. Parar/esperar workers antigos. Manter temporariamente os nomes antigos de tarefas como consumidores de compatibilidade que apenas registram desativação, sem chamada nacional nem conversão em pedido ATF. Preservar no snapshot o motivo de interrupção dos pedidos. Filas pendentes e redeliveries precisam de tratamento explícito, sem purgar uploads de certificados na mesma fila.
2. Fazer backup consistente do banco e do armazenamento, com manifesto de checksums e ensaio de restauração. Registrar pedidos antigos em execução/espera e a última situação conhecida.
3. Adicionar modelos novos e `LegacyFiscalRecord` sem remover tabelas antigas. Exportar cada registro antigo com tipo, PK, empresa, campos, relações e arquivos. Conferir contagens, integridade e existência/checksum dos arquivos; ausências preexistentes precisam ficar visíveis, não ser inventadas como recuperadas.
4. Reconciliar banco e cofre A1. O teste encontrou identificadores de armazenamento diferentes entre o SQLite e o cofre. Não apontar o cadastro ao único arquivo por conveniência: comparar fingerprint, CNPJ, validade e senha verificável. Normalizar separadores Windows como caminho relativo seguro; manter UUID e AAD consistentes. Quando não houver correspondência comprovada, requerer novo cadastro de A1 pelo fluxo normal, sem tentativa com outro certificado.
5. Adaptar as recorrências para `DownloadPolicy`, preservando modo, frequência, horário, fuso, dias configurados e estado ativo/inativo. Aplicar o mapeamento de período acima e XML+TXT como formatos iniciais editáveis. Pausar somente o despachante global durante o corte e retomá-lo depois, sem exigir reativação manual das políticas anteriormente ativas. Decisões de período e formatos não podem ser inferidas de um cursor antigo.
6. Trocar tarefas, rotas e interface pelo domínio novo. Expor histórico legado somente para leitura e download autorizado, preservando ambiente de origem inclusive `unknown`.
7. Após reconciliação validada e ensaio de restauração, remover modelos/tabelas antigos em migrations adicionais e apagar código exclusivo. Preservar a auditoria existente e os snapshots legados. Uma falha de reconciliação bloqueia apenas a etapa destrutiva, não autoriza perda de dados.

Os consumidores de compatibilidade são transitórios. Removê-los somente após comprovar ausência de tarefas antigas prontas, reservadas, ativas, agendadas e não confirmadas em todos os workers/broker, e decorrer a maior janela entre redelivery configurado e ETA/retry pendente conhecido. Retirar também o agendamento antigo do beat. A entrega final não mantém wrappers SOAP, NSU ou tarefas antigas indefinidamente.

Antes do corte, rollback é voltar ao código antigo com backup intacto e chamadas remotas desabilitadas. Após novos pedidos, rollback não pode restaurar um backup antigo descartando pedidos ou reenviar solicitações: pausar o worker novo, preservar banco/arquivos correntes e aplicar correção adiante ou restaurar em ambiente separado para reconciliação.

## Aceite

- Uma empresa com A1 válido solicita XML e TXT por período e recebe os ZIPs correspondentes, com retomada após reinício do worker.
- O download automático programável continua disponível e retoma os agendamentos existentes após o corte, preservando suas configurações e sem conversão forçada para modo manual.
- Períodos, empresas e formatos não se misturam; nenhuma rota ou admin permite acesso cruzado de escritório.
- Notas, eventos e relatórios são preservados separadamente; duplicidade, período vazio, arquivos inválidos e resultado parcial são distinguíveis.
- Não há consulta nacional, NSU, SOAP, homologação fictícia ou correção de cursor no runtime novo.
- Instalação nova e atualização do banco existente passam; histórico e arquivos antigos permanecem consultáveis.
- Testes automáticos são offline e sintéticos. Testes de locks precisam de PostgreSQL real. Um smoke real usa A1 do cofre e datas explícitas, apenas para consultas/downloads, sem ação fiscal de emissão/cancelamento/manifestação.

## Limites e escolhas deixadas à implementação

Não entram outras UFs/portais, A3, certificado do contador, manifestação fiscal, emissão ou cancelamento de notas, interpretação contábil completa do TXT, notificações externas ou exclusão automática de históricos. A implementação pode escolher funções auxiliares e apresentação consistente com o design existente, mas não substituir os contratos de sessão, retenção, isolamento e migração definidos aqui.

Confirmar em smoke posteriores o significado exato das mensagens sem anexo, paginação, dados de identidade da conta remota e códigos de erro do portal. Até haver evidência, ausência de anexo isolada é pendência ou falha de processamento, não prova de período vazio; conteúdo ambíguo não libera arquivo nem provoca reenvio automático.
# Revisão de escopo — 20/10/2026

Prevalecem as diretrizes da revisão de 20/10/2026 no plano de implementação: legado fiscal sem exigência de preservação, extração e exibição de número da nota no XML, estrutura por CNPJ/formato/data da solicitação, tolerância à lentidão e reagendamento automático após tentativas esgotadas para tarefas programadas, histórico por empresa com usuário manual e datas inicial/final obrigatórias. Cadastros, certificados, isolamento por escritório e agendamento programável permanecem.
