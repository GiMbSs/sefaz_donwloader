# Validação real ATF-PB — 21/10/2026

Todas as novas consultas desta validação usam **21/10/2026 a 21/10/2026**, no
fuso America/Fortaleza, com o A1 existente da empresa. A autenticação e as
respostas abaixo são reais. Não foram feitas operações de emissão,
cancelamento ou manifestação fiscal.

## Como os testes foram executados

- Banco e arquivos isolados em `.runtime/atf-real-2026-10-21/`, fora do Git.
  Cadastros e agendamentos da instalação do cliente não foram alterados.
- Certificado e senha recuperados do cofre cifrado; a chave privada não foi
  exportada para disco. O navegador recebeu o A1 em memória.
- Pedidos manuais criados pelo serviço `request_download`; pedidos automáticos
  criados por `enqueue_due_downloads`, ambos processados por `advance_part` com
  HTTP real e `dispatch=False`.
- O agendamento de produção usa dias completos. Apenas no teste isolado, a
  ocorrência do calendário foi controlada para 22/10/2026 00:01, fazendo a
  estratégia de dia anterior consultar exclusivamente o dia real 21/10/2026.
  O relógio das chamadas à SEFAZ e dos intervalos de espera permaneceu real.
- Não havia serviços Compose em execução. Este teste valida o motor e os
  acessos reais, **não** uma execução completa de Celery/Redis/beat em produção.
- As verificações do motor respeitaram o intervalo mínimo de 60 segundos.
  Houve falhas transitórias de conexão antes do envio, seguidas de retomada.

## Matriz pelo motor atual

| Origem | Modelo | Formato | Resposta real |
| --- | --- | --- | --- |
| Manual | NF-e | TXT | Aceita; grupo `104758311`, sem registros |
| Manual | NF-e | XML | Aceita; grupo `104759002`, sem registros |
| Agendada | NF-e | TXT | Aceita; grupo `104759567`, sem registros |
| Agendada | NF-e | XML | Aceita; grupo `104759761`, sem registros |
| Manual | NFC-e | TXT | Rejeitada por CAPTCHA, código remoto `3291` |
| Manual | NFC-e | XML | Rejeitada por CAPTCHA, código remoto `3291` |
| Agendada | NFC-e | TXT | Rejeitada por CAPTCHA, código remoto `3291` |
| Agendada | NFC-e | XML | Rejeitada por CAPTCHA, código remoto `3291` |

As consultas NF-e sem registros não produziram ZIP. Os grupos possuíam três
mensagens: início, **“Nenhum registro satisfaz a pesquisa”**, e fim. A SEFAZ
envolve a resposta sem registros em texto de erro de execução do método;
isso não representa falha de autenticação ou arquivo ainda em geração.

Essas mensagens omitem CNPJ, período e formato. O horário e a diferença em
relação à caixa anterior identificam candidatos, mas não comprovam autoria
quando há outras consultas no portal. Por isso o código apresenta
`atf_empty_requires_review` e **Conferir resultado**. O encerramento sem notas
exige vínculo confirmado pelo administrador ou evidência completa dos filtros.
Os grupos desta validação isolada foram revisados explicitamente e vinculados
ao usuário de teste, com auditoria. Não se deve interpretar esse encerramento
como conciliação inteiramente automática de respostas sem filtros.

A primeira NFC-e/TXT reproduziu o comportamento antigo de envio incerto. Após
ler a mensagem oficial do código `3291` — **“Falha ao validar o Captcha”** —,
essa tentativa isolada foi encerrada com justificativa, sem reenvio incerto.
Nas chamadas seguintes, a rejeição já foi classificada como
`atf_captcha_required`, sem aguardar um ZIP inexistente ou deixar barreiras de
submissão pendentes.

## Teste adicional no navegador oficial

O formulário NFC-e foi preenchido normalmente, com CNPJ do A1, mesmas datas
e tipos de exibição TXT/XML. O botão oficial executou a validação reCAPTCHA
do próprio portal. Nos dois testes houve confirmação de envio e criação de
grupos `FIS_1484`. Não foi necessária uma intervenção humana nesses dois
acessos; isso não garante dispensa de desafio em outras sessões.

| Formato | Grupo | Anexo real | Conferência |
| --- | --- | --- | --- |
| TXT | `104759302` | `NFCE_20261021172135.txt`, 28.592 bytes | 84 notas; CP1252; CNPJ, modelo 65, chave, número e emissão em 21/10/2026 conferidos |
| XML | `104759383` | `NFCE_XML_RGK5XDWJ3B.zip`, 387.945 bytes | 85 XMLs de notas do modelo 65, CNPJ, chave, número e emissão em 21/10/2026 conferidos |

O TXT veio diretamente como `application/txt`, **sem ZIP**. O ZIP XML contém
85 XMLs e um auxiliar vazio `CHAVES_NAO_ENCONTRADAS.txt`. Os nomes e os bytes
originais foram preservados em
`.runtime/atf-real-2026-10-21/browser-downloads/{txt,xml}/`.

As consultas ocorreram em momentos diferentes (17:21 e 17:24). As contagens
84/85 são as observadas em cada resposta; não foi provado que a diferença
represente perda de documentos. A validação do XML permanece com
`pending_schema` e `nonstandard_xml_namespace`: a conferência de identidade
e conteúdo não equivale à validação completa do XSD ou da assinatura.

Os grupos NFC-e tinham quatro notificações: aguardar fila, início, anexo e fim.
A mensagem de espera permanece no grupo mesmo após o anexo estar pronto.
A quantidade de mensagens ajuda a localizar o retorno, mas não substitui a
leitura do conteúdo e a validação dos anexos.

## Correções incluídas

- Leitura de HTML declarado UTF-8 mas efetivamente recebido em CP1252,
  evitando falso envio incerto quando a confirmação contém “será”.
- Reconhecimento da resposta explícita sem registros, incluindo o invólucro
  de erro do método usado pela SEFAZ.
- Identificação de candidatos sem filtros e conferência administrativa,
  incluindo confirmação posterior de vínculo criado automaticamente.
- Diagnóstico específico para CAPTCHA rejeitado. Falha, limpeza da intenção
  rejeitada e liberação de barreiras são persistidas na mesma transação.
- Consulta aceita limpa o erro transitório anterior da etapa atual.
- Exportação XML NFC-e aceita apenas o auxiliar conhecido e vazio, mantendo-o
  no ZIP original. Auxiliar não vazio ou outro TXT continuam rejeitados.

## Pendências comprovadas para a integração

1. Integrar o fluxo oficial de navegador à submissão NFC-e, com A1 protegido,
   intervalos, exclusão mútua e tratamento de eventual desafio que exija usuário.
   O cliente HTTP atual não realiza essa validação; a NFC-e automática ainda
   não está funcional de ponta a ponta.
2. Aceitar TXT direto como anexo original, preservando nome/bytes e aplicando a
   validação existente. O pipeline de armazenamento atual exige ZIP; não se
   deve renomear um TXT para ZIP nem confundir cópia de processamento com original.
3. Adaptar a conciliação de anexos sem filtros: as mensagens NFC-e observadas
   também omitem período. Mesmo após a confirmação administrativa, a entrega
   atual exige período na mensagem. A integração deve validar o arquivo antes
   de publicar, preservando CNPJ, modelo, formato, período e vínculo do pedido.
4. Automatizar a conclusão sem notas apenas com evidência suficiente para
   vincular o retorno. Enquanto a SEFAZ omitir os filtros, há conferência
   administrativa explícita; não considerar apenas horário ou quantidade de filhos.
5. Repetir a matriz pelo Compose com worker/beat após essas adaptações. Os
   testes reais deste documento não comprovam a infraestrutura de filas ativa.

Não há oito downloads bem-sucedidos: NF-e não tinha notas; NFC-e expôs
rejeição de CAPTCHA no motor atual. Os dois anexos NFC-e baixados vieram do
teste adicional no formulário oficial, ainda não integrado ao produto.

## Verificação das correções

- SQLite: **401 testes aprovados**, 11 testes de bloqueios concorrentes
  reservados ao PostgreSQL.
- PostgreSQL 17 descartável: **412 testes aprovados**, incluindo concorrência.
  Instância temporária sem volumes do cliente, removida ao encerrar a validação.
- Ruff, mypy (76 arquivos), `manage.py check` e verificação de migrations sem
  pendências. Nenhuma migration nova necessária.
- Revisão independente das mudanças de correlação, confirmação administrativa,
  rejeição de CAPTCHA e auxiliar vazio do ZIP sem achados P1/P2 remanescentes.

As regressões exercitam NF-e/NFC-e, XML/TXT, origens manual/agendada, falta de
filtros, confirmação administrativa, vínculos automáticos sem confirmação,
quantidade de filhos insuficiente, horário incompatível, CAPTCHA rejeitado e
TXT auxiliar não vazio/desconhecido. Não substituem as pendências de integração
real listadas acima.
