# PRD e plano de implementação — Downloader DF-e para contabilidade

## 1. Visão do produto

Aplicação web local, executada em containers Docker, para escritórios de
contabilidade cadastrarem empresas clientes, manterem seus certificados A1 de
forma segura e obterem documentos fiscais eletrônicos diretamente dos serviços
oficiais. A primeira praça comercial é a Paraíba, sem limitar o desenho aos
demais estados.

O produto é uma estação de trabalho contábil: oferece operação fiscal,
consulta, rastreabilidade e alertas. Não é um explorador de diretórios nem um
emissor de notas.

## 2. Objetivos

- Baixar e preservar XMLs de NF-e e, após validação em campo, NFC-e para cada
  empresa cliente.
- Permitir sincronização automática diária, manual ou híbrida por empresa.
- Controlar NSU de forma segura, detectar inconsistências e alertar o escritório
  sem causar consumo indevido na SEFAZ.
- Compartilhar os XMLs baixados em pasta do computador hospedeiro, fora do
  ciclo de vida dos containers.
- Guardar evidências suficientes para auditoria: origem, lote, XML original,
  validações, usuário e ações operacionais.
- Manter o núcleo fiscal extensível por UF, modelo de documento e autorizador.

## 3. Escopo do MVP

### Incluído

- Python 3.13 e Django 6.
- PostgreSQL, Redis, worker assíncrono e agendador único em Docker Compose.
- Usuários com os papéis Administrador e Operador.
- Cadastro de escritório contábil, empresas, matriz/filiais, ambiente e
  configurações de sincronização.
- Certificado A1/PFX por empresa, com conferência de titularidade, validade e
  CNPJ-base.
- Captura pelo `NFeDistribuicaoDFe`, controle de `ultNSU`, lote bruto e
  processamento idempotente.
- Armazenamento e consulta de XML original, resumos e eventos recebidos.
- Validação segura de XML, XSD oficial e, quando aplicável, assinatura XMLDSig.
- Pasta externa configurável para os XMLs baixados.
- Painel operacional, busca, download autorizado, fila, alertas e auditoria.
- Perfil inicial da Paraíba e catálogo de capacidades para expansão posterior.

### Fora do MVP

- Emissão, cancelamento ou retransmissão de NF-e/NFC-e.
- Manifestação automática. Uma manifestação fiscal só poderá ser incluída em
  fase posterior, com confirmação explícita por empresa e trilha de auditoria.
- Certificados A3/token; exigem agente local e interação física/PIN, não são
  adequados ao worker Docker inicial.
- CT-e, MDF-e, NFS-e, NFCom e demais DF-e.
- API pública, recebimento por e-mail, aplicativo móvel e integrações com ERP.

## 4. Regras fiscais e operacionais obrigatórias

### 4.1 Distribuição e NSU

1. O cursor é persistido por empresa, ambiente e serviço; não pode ser alterado
   livremente pela interface.
2. Toda consulta subsequente usa exclusivamente o `ultNSU` retornado na última
   resposta persistida.
3. Ao receber `cStat=137`, a próxima consulta só pode ocorrer após uma hora.
4. Ao receber `cStat=656`, a empresa fica bloqueada localmente por, no mínimo,
   uma hora; o motivo e a previsão de desbloqueio devem aparecer no painel.
5. Somente um worker pode consultar um mesmo cursor de cada vez. Usar trava
   transacional/advisory lock no PostgreSQL.
6. A resposta SOAP e cada `docZip` são arquivados antes de avançar o cursor.
   Falhas locais devem permitir reprocessamento sem nova consulta à SEFAZ.
7. Lacuna, salto inesperado de NSU, XML inválido, falha de armazenamento ou
   certificado vencido criam alerta de operação.

### 4.2 Agendamento por empresa

Cada empresa terá uma `PoliticaSincronizacao` com:

- modo: `AUTOMATICA_DIARIA`, `MANUAL` ou `HIBRIDA`;
- horário, fuso horário, dias ativos, estado ativo/pausado e tentativas;
- última execução, próxima execução desejada e próxima consulta permitida pela
  SEFAZ;
- último resultado, contador de falhas e destinatários de alertas.

O botão "Solicitar sincronização" cria uma requisição assíncrona auditável. Ele
não chama a SEFAZ dentro da requisição HTTP e não ignora espera de 137/656. Se
já houver tarefa em fila ou execução para a empresa, a solicitação é agrupada.

A primeira sincronização pode consumir os lotes sequenciais permitidos até não
haver mais documentos; a rotina diária posterior busca apenas o que estiver
disponível e respeita o bloqueio de consumo.

### 4.3 Documentos completos, resumos e manifestações

O sistema distingue documento resumido de XML completo. `resNFe` ou outro
resumo prova que houve descoberta, mas não é apresentado como XML fiscal
completo. Quando a disponibilidade do XML depender de manifestação, a tela
informa o estado e permite que um operador autorizado trate a situação fora do
MVP; nenhuma ciência ou confirmação é enviada automaticamente.

## 5. Perfil inicial: Paraíba

### Decisões de produto

- O Ambiente Nacional é a fonte normal do `NFeDistribuicaoDFe`; não haverá
  automação de portais web, CAPTCHAs ou consultas humanas da SEFAZ-PB.
- Paraíba/SVRS entra como perfil de autorizador e consulta, separado da
  distribuição nacional. Endpoints são mantidos em catálogo versionado, nunca
  codificados em views ou tarefas.
- NFC-e modelo 65 estará no modelo de dados, filtros, armazenamento e testes.
  A captura automática só será anunciada após teste controlado com empresa PB e
  evidência real do serviço.
- O sistema não solicita nem guarda CSC: é segredo de emissão/QR Code de NFC-e,
  fora do escopo de download.
- XMLs de NF-e e NFC-e de clientes PB têm retenção padrão mínima de 132 meses
  contados da autorização. Antes desse prazo não há expurgo automático.
- Uma empresa sediada na PB pode receber documentos emitidos em outras UFs; a
  busca não filtra documentos pelo código da Paraíba. Armazenar UF da empresa e
  UF/autorizador do documento separadamente.
- Documentos próprios emitidos pelo cliente não são tratados como garantidos
  apenas pela distribuição. O desenho prevê uma fonte complementar de pasta
  monitorada, a ser habilitada em fase posterior.

### Matriz inicial de capacidade

| Item | Estado no lançamento PB | Observação |
| --- | --- | --- |
| NF-e modelo 55 de interesse da empresa | Habilitado | Via distribuição nacional e NSU. |
| NFC-e modelo 65 | Piloto controlado | Liberar após prova de cobertura real. |
| XML de saída do ERP do cliente | Planejado | Pasta monitorada, com origem identificada. |
| Manifestação do destinatário | Fora do MVP | Ação fiscal explícita, nunca automática. |
| A3/token | Fora do MVP | Depende de agente local seguro. |

## 6. Segurança de certificados e segredos

Uma senha de PFX guardada somente como hash não permite automação, pois hash não
é recuperável para abrir o certificado. Para manter o banco sem senha reversível
e ainda permitir a assinatura automática, o sistema deve:

1. Persistir no banco somente `password_hash`, produzido pelos hashers do Django.
2. Cifrar o arquivo PFX e a credencial recuperável com criptografia autenticada
   em arquivos privados de `clientes/<id-da-empresa>/certificados/`.
3. Manter a chave mestra fora do banco, do código e da imagem Docker, injetada
   como segredo protegido no host.
4. Montar certificados somente para o worker; nunca em `MEDIA_URL`, logs,
   backups de interface ou container web.
5. Exibir somente metadados seguros: titular, serial, emissor, CNPJ-base e
   vencimento.
6. Auditar inclusão, substituição, teste, expiração e remoção, sem registrar a
   senha, o conteúdo do PFX ou valores de segredo.

Uploads passam por limite de tamanho, extensão esperada, parsing seguro e
validação real do certificado antes da persistência. Usuários não fornecem um
caminho arbitrário do computador para o servidor abrir.

## 7. Arquitetura técnica

```text
Navegador -> Django web -> PostgreSQL
                    |-> Redis

Agendador -> fila Redis -> worker fiscal -> Ambiente Nacional / autorizadores
                                    |-> volume privado de certificados
                                    `-> bind mount de notas no computador local
```

Serviços Docker:

- `web`: Django, sessões, formulários, consultas e comandos assíncronos.
- `migrations`: cria chaves privadas quando necessário e aplica migrations com
  acesso ao cofre, antes dos serviços de aplicação.
- `worker`: cliente fiscal, XML, armazenamento e reprocessamento.
- `scheduler`: instância única que identifica empresas elegíveis; não executa
  em processos web.
- `postgres`: estado transacional, auditoria e índices de consulta.
- `redis`: fila e coordenação de tarefas.

Banco e Redis não expõem portas ao host. Apenas o serviço web é publicado. Em
produção, usar proxy HTTPS e configurações de segurança do Django.

### Volumes

- `NOTES_HOST_DIR:/dados/notas`: bind mount de escrita do worker e leitura
  controlada pelo web; contém XMLs baixados e estrutura previsível por empresa,
  período, modelo e chave de acesso.
- `CERTIFICATES_HOST_DIR:/dados/certificados`: volume privado, cifrado e sem
  acesso HTTP direto.
- volume nomeado do PostgreSQL: não substitui backups.

Arquivos são escritos de forma atômica, recebem SHA-256 e são deduplicados por
empresa e chave de acesso. O nome de arquivo nunca é aceito diretamente de uma
entrada do usuário.

## 8. Modelo de domínio

- `EscritorioContabil`: tenant inicial da instalação.
- `EmpresaCliente`: CNPJ, matriz/filial, UF, ambiente, estado e política.
- `CertificadoDigital`: metadados, `password_hash` e referências aos arquivos
  privados e cifrados de PFX e credencial.
- `PoliticaSincronizacao`: agenda, modo, estado e janelas permitidas.
- `ControleNSU`: cursor, `maxNSU`, bloqueios e última resposta.
- `LoteDistribuicao`: requisição, resposta, hashes, NSUs, versão de schema e
  estado de processamento.
- `DocumentoFiscal`: empresa, chave, modelo, tipo, emissão, autorizador, XML,
  hash, estado de validação e caminho externo.
- `Alerta`: severidade, contexto, estado e resolução.
- `Auditoria`: ator, ação, objeto, data, correlação e resultado.

Criar usuário customizado em `accounts` na primeira migration e referenciá-lo
com `settings.AUTH_USER_MODEL` em todas as relações.

## 9. Interface

### Administrador

- empresas, certificados, usuários, políticas, armazenamento e alertas;
- visualização de NSU, bloqueios e histórico de lotes;
- criação de solicitações e reprocessamentos idempotentes;
- resolução registrada de alertas.

### Operador

- painel de trabalho, busca e download autorizado;
- acompanhamento de sincronizações e alertas atribuídos;
- solicitação manual respeitando as políticas;
- sem alteração de cursor, segredo, bloqueio fiscal ou permissões.

As telas devem usar HTML semântico, rótulos claros, foco por teclado,
mensagens acessíveis e comportamento responsivo. Formulários usam CSRF e toda
autorização é revalidada no servidor.

## 10. Validação de XML

1. Fixar os pacotes XSD oficiais em `vendor/sefaz-schemas/`, com manifesto de
   versão, data de obtenção e checksum.
2. Usar parser sem resolução externa de entidades e com limites de tamanho,
   profundidade e descompressão de `docZip`.
3. Validar envelope/resposta de distribuição e o XML interno pelo XSD adequado.
4. Em documentos assinados, validar XMLDSig e registrar separadamente resultado
   de schema, assinatura, certificado e integridade.
5. Preservar sempre os bytes originais; metadados extraídos não substituem o
   XML fiscal.
6. Aceitar CNPJ numérico e alfanumérico: as 12 primeiras posições podem ser
   alfanuméricas e os dois dígitos verificadores permanecem numéricos. Aplicar
   o cálculo oficial de módulo 11 e armazenar a forma canônica sem pontuação.
   Chaves de acesso e XMLs continuam sujeitos aos respectivos XSDs oficiais.

## 11. Fases de implementação

### Fase 0 — contratos e fixtures

- Confirmar matriz PB para NF-e/NFC-e com certificado autorizado.
- Baixar e fixar schemas oficiais vigentes.
- Obter fixtures sanitizadas: completo, resumo, evento, denegado, 137, 656,
  XML inválido e documento com campos alfanuméricos.
- Definir política de backup e retenção de 132 meses.

### Fase 1 — fundação

- Criar projeto Django, settings por ambiente, Docker Compose e CI.
- Configurar PostgreSQL, Redis, worker, scheduler e usuário customizado.
- Implementar autenticação, grupos, auditoria e configuração segura.

### Fase 2 — cadastros e cofre de certificados

- Empresas, matriz/filiais, política de sincronização e telas.
- Upload seguro, cifragem, inspeção e alerta de vencimento de A1.
- Testes de permissão, isolamento por empresa e não exposição de segredo.

### Fase 3 — núcleo de distribuição

- Cliente SOAP/TLS, catálogo de endpoint, XSD e XMLDSig.
- Controle NSU, lote atômico, deduplicação, locks e reprocessamento.
- Tratamento de 137/656, erros transitórios e alertas.

### Fase 4 — operação web e arquivos

- Painel, busca, download autenticado, histórico e resolução de alerta.
- Bind mount de notas, escrita atômica, ZIP autorizado e teste de restauração.
- Configuração diária/manual/híbrida por empresa.

### Fase 5 — homologação PB e lançamento controlado

- Testar NF-e modelo 55 em ambiente permitido e validar recuperação após
  falha/reinício.
- Executar piloto NFC-e modelo 65 antes de habilitar sua venda automática.
- Rodar backup/restauração, teste de volume e revisão de segurança.
- Documentar evidências, limitações e procedimento de suporte.

### Fase 6 — expansão planejada

- Pasta de entrada monitorada para XML emitido por ERP.
- Relatórios TXT de NF-e/NFC-e emitidas por fonte identificada, conforme o
  [plano de execução](PLANO-RELATORIOS-TXT-EMITIDOS.md). O TXT é complementar
  e não substitui XML autorizado.
- API, integrações, notificações e e-mail de recepção.
- Manifestação assistida, somente após desenho fiscal e jurídico aprovado.
- Novas UFs por perfil de capacidade e suíte de testes específica.

## 12. Qualidade e critérios de aceite

- `ruff`, `mypy`, `pytest`, teste de migrations e testes de integração.
- Testes para idempotência, exclusão de duplicidade, locks, saltos de NSU,
  137/656, falha de rede, falha de disco e reprocessamento de lote.
- Testes de XSD, XMLDSig, documentos compactados maliciosos e upload inválido.
- Testes de interface em desktop/mobile, navegação por teclado e sem erros JS.
- `manage.py check --deploy`, variáveis secretas fora do repositório e HTTPS
  no ambiente exposto.
- `docker compose config` valida a configuração; a execução real é validada em
  host com daemon Docker e com dados de teste não sensíveis.
- Nenhuma conclusão de suporte NFC-e, cobertura de saída ou produção será feita
  sem evidência de teste controlado registrada na documentação.

## 13. Referências oficiais consultadas

- [Portal Nacional — schemas XML NF-e](https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?AspxAutoDetectCookieSupport=1&tipoConteudo=BMPFMBoln3w%3D)
- [Portal Nacional — relação de web services](https://www.nfe.fazenda.gov.br/PORTAL/WebServices.aspx?AspxAutoDetectCookieSupport=1&tipoConteudo=OUC%2FYVNWZfo%3D)
- [SEFAZ-PB — NF-e](https://portal.sefaz.pb.gov.br/info/notas-fiscais/nf-e)
- [SEFAZ-PB — NFC-e](https://sefaz.pb.gov.br/info/notas-fiscais/nfc-e)
- [SEFAZ-PB — Decreto nº 46.489/2025](https://www.sefaz.pb.gov.br/legislacao/379-decretos-estaduais/icms/icms-2025/16253-decreto-n-46-489-de-29-de-abril-de-2025)
- [Receita Federal — CNPJ Alfanumérico](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/cnpj-alfanumerico)
- [Django 6.0 — deployment checklist](https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/)
