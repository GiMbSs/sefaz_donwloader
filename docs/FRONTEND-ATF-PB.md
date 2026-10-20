# Revisão do frontend ATF-PB

## Causa e correção

O diretório principal ainda executava o domínio nacional antigo. A implementação ATF-PB estava isolada em `.worktrees/atf-pb`. Em 20/10/2026, o código atual e suas migrações foram consolidados na raiz, preservando a alteração local de `.dockerignore` e sem modificar `.env`, bancos, certificados ou arquivos do cliente.

Trocar apenas os textos não resolveria as validações antigas: formulários, views, rotas e modelos precisavam corresponder ao fluxo ATF-PB. O código consolidado inclui a retirada do motor SOAP/NSU já implementada e os downloads NF-e/NFC-e.

## Fluxos revisados

- Cadastro e edição de empresa: CNPJ, dados cadastrais, escritório e situação; sem NSU inicial ou ambiente fiscal. O certificado A1 pode ser cadastrado junto ou posteriormente.
- Lista e detalhe da empresa: sem coluna de produção/homologação ou controles de NSU; acesso ao certificado, agendamento, pedidos e documentos.
- Download manual: modelo NF-e/NFC-e, datas inicial/final obrigatórias e formatos XML/TXT; usuário solicitante registrado.
- Agendamento: modelos, formatos, período, frequência e horário; sem recuperação automática de NSU ou controles do motor anterior.
- Painel e histórico: pedidos por período, identificação NF-e/NFC-e e estados da SEFAZ-PB. O painel agora distingue pedidos dos dois modelos para a mesma empresa e período.
- Documentos: notas, eventos e TXT, com filtro por modelo; sem documentos resumidos do serviço nacional.
- Administração técnica: os modelos e ações de promoção de ambiente do domínio anterior foram retirados. Rotas antigas de operação retornam encerramento, sem formulário legado.

## Validação e instalação

Os testes de regressão reproduziram o cadastro legado e a navegação desatualizada na raiz, além da coluna de ambiente e da falta de identificação do modelo no painel. A correção é verificada pela suíte do diretório principal.

Uma instalação já em execução precisa usar a imagem/código atual e suas migrações. Este trabalho não aplica migrações ao banco do cliente nem reinicia a instalação. As migrações existentes retiram os dados fiscais antigos conforme a autorização anterior, preservando cadastros e certificados.

Resultados: 152 testes passaram no SQLite, com um teste específico de locks ignorado; 153 passaram no PostgreSQL descartável. Após os ajustes finais de rótulos, os 28 testes de telas e permissões passaram novamente. Ruff, formatação, mypy (83 arquivos), Django check e ausência de drift nas migrações passaram.

Foram conferidas sete telas no Chromium em 1440 px e 390 px: cadastro, edição, agendamento, pedido manual, lista de empresas, histórico e documentos. Todas responderam corretamente, sem campos antigos ou transbordamento horizontal da página. Painel, cadastro e agendamento também foram inspecionados visualmente. Capturas locais em `output/playwright/frontend-atf-*.png`.

O diff dos arquivos alterados passa na verificação de espaços. A `.dockerignore` já estava alterada com finais de linha CRLF e foi preservada byte a byte; seus avisos preexistentes não foram corrigidos como efeito colateral desta tarefa.
