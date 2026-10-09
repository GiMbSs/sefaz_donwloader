# Plano de execução — relatórios TXT de documentos emitidos

## Objetivo

Disponibilizar à contabilidade, de forma rastreável e isolada por empresa, os
relatórios de NF-e modelo 55 e NFC-e modelo 65 emitidas pelo cliente. A origem
funcional dos dois arquivos foi confirmada pela contabilidade como SEFAZ, no
perfil inicial da Paraíba. A primeira entrega automatiza a importação dos TXT
exportados da SEFAZ pelo operador; ela não substitui XML fiscal autorizado, não
altera o fluxo de distribuição de DF-e e não acessa automaticamente portais
autenticados.

Os exemplos recebidos são layouts distintos, delimitados por `|` e codificados
em ISO-8859-1:

| Layout | Modelo | Linhas de dados no exemplo | Colunas |
| --- | ---: | ---: | ---: |
| `NFE_EMIT` | 55 | 23 | 39 |
| `NFCE_*` | 65 | 7.710 | 51 |

Os códigos de situação serão armazenados como recebidos. Não serão convertidos
em regra fiscal enquanto sua legenda e semântica forem confirmadas pela fonte.

## Limites inegociáveis

- O TXT é um relatório complementar de conciliação; `nfeProc`/XML autorizado
  continua sendo o artefato fiscal primário.
- Importar um TXT não cria, substitui nem valida um XML, não dispara
  manifestação e não avança `ControleNSU`.
- Cada arquivo, linha, erro e download deve estar associado à empresa cliente;
  não haverá consulta ou reutilização entre tenants.
- O worker, e não a requisição web, processa a pasta de entrada.
- Não haverá automação de navegador, CAPTCHA, sessão, cookie ou credencial do
  SERvirtual. Um conector direto só poderá existir após confirmação documental
  da SEFAZ-PB de interface autorizada para automação.
- Os exemplos atuais possuem dados fiscais e pessoais. Eles não serão usados
  como fixtures nem copiados para testes, logs ou imagens de container.

## Entrega inicial proposta

1. O operador autorizado coloca o TXT original em uma pasta privada de entrada
   da empresa, fora do repositório e fora de `MEDIA_URL`.
2. O worker detecta, copia e arquiva os bytes originais de maneira atômica.
3. O parser reconhece o layout por assinatura de cabeçalho e versão, valida a
   codificação, a chave de acesso, o modelo e os campos obrigatórios.
4. As linhas são persistidas como relatório de documentos emitidos, preservando
   valores brutos e valores normalizados quando o contrato permitir.
5. A interface mostra o relatório, sua origem, período, contagens, erros e a
   situação de conciliação com XML já arquivado. A ausência de XML é exibida
   como pendência; não é preenchida com dados do TXT.

O resultado atende o fluxo contábil sem depender de uma automação frágil do
portal e preserva um ponto de integração futuro para XML de saída do ERP.

## Fase 0 — confirmar fonte e higienizar artefatos

**Responsáveis:** cliente/contabilidade e operador técnico.

1. Registrar a confirmação do cliente de que os dois layouts são exportados
   pela SEFAZ e identificar, para cada um, a URL e o caminho de menu usados
   para exportação, filtros aplicados, periodicidade e se o arquivo é diário,
   mensal ou sob demanda. Não enviar senha, certificado, cookie ou sessão.
2. Confirmar qual resultado a contabilidade espera: download do TXT original,
   painel de conciliação, XML emitido, ou arquivo em leiaute do ERP contábil.
   Para este último, informar nome, versão e manual do sistema destinatário.
3. Obter a documentação, manual ou resposta formal da fonte que identifique
   os campos e os significados de situação (inclusive `A`, `C` e `O`).
4. Substituir os exemplos versionados por fixtures anonimizadas em uma tarefa
   de segurança separada e guardar os originais em volume protegido. Caso o
   repositório já tenha sido publicado, avaliar a limpeza do histórico antes
   de qualquer divulgação adicional.

**Gate G0:** a origem SEFAZ dos dois layouts e a finalidade do arquivo estão
registradas; o serviço/caminho exato de cada exportação foi identificado, existe
ao menos um fixture anonimizável e o cliente confirmou que a primeira entrega
pode usar pasta monitorada/upload, sem automação do portal.

## Fase 1 — contrato de importação e modelo de dados

**Implementação:** contrato versionado e migrations incrementais.

1. Criar uma entidade de lote de relatório, por exemplo
   `RelatorioEmitidoImportado`, contendo empresa, fonte declarada, modelo,
   versão de layout, codificação, caminho externo, SHA-256, período informado,
   contagens, estado, erros e auditoria.
2. Criar uma entidade de linha, por exemplo `LinhaRelatorioEmitido`, com lote,
   chave de acesso, modelo, número, série, emissão, situação bruta, total
   bruto/normalizado e conteúdo bruto da linha. Os campos exclusivos de cada
   layout ficam versionados, sem forçar uma falsa equivalência entre NF-e e
   NFC-e.
3. Definir unicidade idempotente por empresa, assinatura do arquivo e linha;
   a mesma remessa não deve gerar duplicidade. Uma nova versão recebida deve
   permanecer auditável, não sobrescrever silenciosamente a anterior.
4. Definir uma assinatura fechada para cada cabeçalho aceito. Cabeçalho ou
   codificação desconhecidos devem deixar o lote em quarentena, sem importar
   parcialmente.
5. Registrar em documentação a política de retenção, acesso e mascaramento de
   identificadores exibidos na interface.

**Critérios de aceite:** migrations reversíveis em ambiente de teste; nenhum
novo modelo altera `ControleNSU`, `LoteDistribuicao` ou o XML armazenado; os
dados são sempre filtrados por empresa.

## Fase 2 — recebimento e parser seguro

**Implementação:** worker de importação local, sem tráfego à SEFAZ.

1. Configurar uma pasta privada por empresa e uma convenção de estados
   (`entrada`, `processando`, `arquivados`, `quarentena`) no volume de notas.
   O nome enviado pelo usuário não determina o caminho final.
2. Limitar tamanho, número de linhas e comprimento de campo; rejeitar arquivo
   binário, NUL, cabeçalho duplicado, chave inválida, modelo incompatível e
   linha com quantidade de colunas divergente.
3. Decodificar inicialmente ISO-8859-1 de modo explícito. Outros encodings só
   entram após versão de layout e fixture que os comprovem.
4. Escrever bytes e metadados de forma atômica, calcular SHA-256 antes do
   processamento e manter resultado por linha, inclusive os rejeitados.
5. Enfileirar o processamento no worker com lock por empresa e lote; a tela
   web só solicita a importação e apresenta seu estado.

**Testes obrigatórios:** dois layouts válidos anonimizados, acentos
ISO-8859-1, repetição idempotente, chave de 44 dígitos inválida, cabeçalho
desconhecido, linha truncada, excesso de tamanho, falha de disco e isolamento
entre duas empresas.

**Gate G2:** cada arquivo de teste pode ser reimportado sem duplicar linhas;
arquivos inválidos não geram documentos fiscais nem modificam NSU.

## Fase 3 — consulta e conciliação operacional

**Implementação:** telas e consultas somente para o tenant autorizado.

1. Exibir lote, origem, período, modelo, situação bruta, totais, quantidade de
   erros e hash, sem expor conteúdo para usuários sem permissão.
2. Relacionar uma linha ao `DocumentoFiscal` existente apenas pela empresa e
   chave de acesso. A relação será de conciliação, não de substituição de
   origem.
3. Exibir estados claros: `XML encontrado`, `XML ausente`, `linha rejeitada` e
   `não conciliável`. Não inferir autorização, cancelamento ou escrituração a
   partir do TXT.
4. Permitir download controlado do TXT original para os papéis autorizados e
   registrar o evento em auditoria.

**Critérios de aceite:** filtros por período/modelo/situação; autorização
server-side; navegação por teclado; nenhuma chave, CPF/CNPJ ou valor de outro
tenant é visível ou pesquisável.

## Fase 4 — validação operacional controlada

**Responsáveis:** operador técnico e contabilidade.

1. Executar a pré-validação existente, backup/restauração e teste de escrita
   do volume antes de habilitar a rotina agendada.
2. Processar cópias protegidas de um arquivo real por layout em ambiente
   autorizado, conferindo contagem, totais e amostra de chaves com a fonte.
3. Simular reentrega do mesmo arquivo, indisponibilidade de volume e arquivo
   parcialmente gravado; registrar alertas e recuperação.
4. Definir frequência de varredura, responsáveis por quarentena e prazo de
   resposta para falhas.
5. Registrar a evidência da execução sem anexar TXT integral, certificados ou
   dados pessoais à documentação do repositório.

**Gate G4:** a contabilidade aprova a conciliação do piloto, a restauração foi
comprovada e alertas/quarentena possuem responsáveis definidos.

## Fase 5 — decisão sobre conector direto à fonte

Esta fase é opcional e não bloqueia a entrega por pasta monitorada.

Só iniciar se forem obtidos todos os itens abaixo:

- URL e serviço exatos de cada exportação;
- contrato público ou autorização formal para acesso automatizado;
- método de autenticação suportado, permissões por empresa e limites de uso;
- versão documentada do leiaute e política de alterações;
- confirmação de que a fonte entrega o relatório necessário e, separadamente,
  o XML de saída quando este for exigido.

Se a fonte não oferecer interface autorizada, a decisão é manter a importação
controlada de arquivos. Não se substitui essa condição por scraping do
SERvirtual. Para XML emitido, a alternativa preferencial continua sendo uma
integração suportada pelo ERP emissor ou uma pasta monitorada de `nfeProc`.

## Sequência de execução e próxima ação

1. Executar a Fase 0 e fechar o Gate G0 com o cliente.
2. Implementar Fases 1 e 2 em um único incremento, com fixtures anonimizadas
   e testes automatizados.
3. Implementar Fase 3 e validar localmente as permissões e a conciliação.
4. Realizar a Fase 4 antes de agendar a rotina para clientes.
5. Avaliar a Fase 5 somente com evidência documental nova.

## Referências consultadas

- [Portal Nacional — NT 2014.002 e distribuição de DF-e](https://www.nfe.fazenda.gov.br/portal/exibirArquivo.aspx?conteudo=U0LlsYVGBRU%3D)
- [SEFAZ-PB — serviços do SERvirtual](https://www.sefaz.pb.gov.br/servirtual)
- [SEFAZ-PB — faturamento diário de NFC-e](https://www.sefaz.pb.gov.br/announcements/6566-receita-estadual-disponibiliza-novo-servico-de-consulta-aos-contribuintes-que-emitem-nfc-e)
