# Operação de downloads SEFAZ-PB

O sistema consulta NF-e (55) e NFC-e (65) emitidas, com certificado A1 individual da empresa. XML e TXT são pedidos separados, entregues pela caixa de mensagens do ATF em ZIP. Não há NSU nem escolha entre homologação e produção.

O pedido manual exige modelo e datas inicial/final. Políticas podem selecionar um ou ambos os modelos; cada modelo gera seu próprio pedido. NFC-e usa partes diárias e janela de geração de sete dias (`ATF_NFCE_WAIT_TIMEOUT_SECONDS=604800`), com consultas progressivamente espaçadas até quinze minutos (`ATF_NFCE_MAX_POLL_INTERVAL_SECONDS=900`). A espera é persistida e retomada após reinício; não mantém um worker ocupado. Mais detalhes em [operação NFC-e](IMPLEMENTACAO-NFCE-PB.md).

## Configuração e corte

1. Manter os volumes de notas e certificados fora do repositório. Preservar chaves do cofre e envelopes de upload. A aplicação web só lê notas e chave pública; somente o worker acessa o A1 e escreve notas.
2. Executar `python manage.py verify_fiscal_installation --worker --write-notes-probe` no worker. O comando não consulta a SEFAZ. A sonda local é removida.
3. Conferir o A1 com `python manage.py reconcile_certificate_vault`. A execução padrão é diagnóstico; aplicar vínculo exige certificado/ator explícitos e identidade criptográfica comprovada. Não selecionar arbitrariamente o primeiro arquivo do diretório.
4. Aplicar migrations em janela de manutenção, com produtores e workers antigos parados e filas antigas drenadas. A migration 0010 adapta o agendamento; a 0013 remove as tabelas fiscais antigas, inclusive os snapshots experimentais, sem exigir exportação do legado. A migration de organizações 0006 remove o ambiente fiscal. Cadastros, usuários, políticas adaptadas e certificados permanecem. Arquivos antigos não são apagados. Não usar reset do banco.
5. Habilitar `ATF_PB_ENABLED=True` após a conferência. `python manage.py probe_atf_pb --company-id ID` autentica e verifica acesso à caixa, sem solicitar relatórios. Para criar pedido pelo comando, informar explicitamente `--submit --actor-id ID --start-date AAAA-MM-DD --end-date AAAA-MM-DD --format both`.

## Pedidos e histórico

Cada empresa possui a tela **Pedidos de download**, acessível por **Ver todos os pedidos** no cadastro. Ela lista todas as solicitações, incluindo agendadas, manuais, falhas e pendentes, com período, formatos, usuário manual, situação e próxima tentativa. O detalhe permite baixar ZIPs, conferir resultados ambíguos e retomar acompanhamento. Datas inicial e final são obrigatórias em pedidos manuais.

O agendamento mantém modo, frequência, horário, fuso, dias da semana/dia do mês e ativação existentes. O período passa a ser dia anterior, mês anterior ou últimos dias completos; não é inferido a partir de NSU. Novas empresas começam no modo manual. Dias mensais inexistentes usam o último dia do mês.

Arquivos ficam em `escritorios/escritorio_<CNPJ do escritório>/empresas/<CNPJ>/XML|TXT/AAAA/MM/DD/<pedido>/<parte>/`. A data é a da solicitação original no fuso da política (ou da instalação), mantida em retomadas. ZIPs originais são identificados por hash; conteúdos separados ficam em `membros/`. IDs evitam colisões entre pedidos no mesmo dia. TXT mantém seus bytes originais.

No download, XML é analisado sem DTD, entidades externas ou acesso de rede. O sistema verifica empresa, modelo, ambiente, período e chave, extrai `ide/nNF` e confere sua correspondência com a chave. Eventos ficam separados de notas; o número da nota aparece na consulta e pode ser pesquisado. Essa conferência não valida assinatura digital nem substitui o XSD completo: o estado `pending_schema` é explícito.

## Lentidão e instabilidade

- Padrão: conexão 10 s, leitura 120 s, lease 300 s, consulta à caixa a cada pelo menos 60 s e janela inicial de resultado de 24 h. Configurar `ATF_CONNECT_TIMEOUT_SECONDS`, `ATF_READ_TIMEOUT_SECONDS`, `ATF_ACCESS_LEASE_SECONDS`, `ATF_POLL_INTERVAL_SECONDS` e `ATF_WAIT_TIMEOUT_SECONDS` conforme necessário; o lease deve superar conexão + leitura + 60 s.
- Erros transitórios recebem até três novas tentativas curtas em 60, 120 e 240 s, considerando Retry-After. O worker não dorme: a próxima etapa é persistida e enfileirada. O scheduler recupera etapas vencidas caso o broker tenha ficado indisponível.
- Ao esgotar esse ciclo, pedidos agendados têm nova tentativa persistida no mesmo pedido/período após pelo menos 30 minutos (`ATF_RETRY_CYCLE_SECONDS`). Ciclos seguintes aumentam o intervalo até 24 h. Desativar a política ou colocar o modo manual interrompe ciclos longos futuros. Pedidos manuais esgotados ficam para retomada explícita.
- POST possivelmente aceito não é reenviado. Barreiras persistentes sobrevivem à expiração do lease, e a retomada busca o resultado existente. Ambiguidades ou conteúdo incompatível exigem conferência administrativa, sem associar automaticamente a mensagem mais recente.
- Falhas permanentes, como certificado indisponível ou mudança do portal, exigem correção; não entram em repetição longa indiscriminada.

## Limites conhecidos

O backend Windows de A1/ACL ainda exige smoke no Windows. Paginação JavaScript e resposta definitiva sem dados ainda não observadas são tratadas conservadoramente. Notas e eventos sem XSD completo permanecem com schema pendente. Logs não devem conter senha, certificado, cookies ou corpo das páginas. Não habilitar consulta de destinatários ou outros modelos neste fluxo.
