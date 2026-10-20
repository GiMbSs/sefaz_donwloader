# Conferência de XML NF-e e NFC-e

## Escopo da revisão

Revisão dos downloads XML, modelos 55 e 65, em continuidade à correção do TXT. O serviço usa o modelo, o CNPJ e o período do pedido para conferir os arquivos antes da publicação.

- CNPJ declarado no emitente e CNPJ contido na chave precisam corresponder à empresa.
- O modelo declarado no XML e o modelo da chave precisam corresponder ao pedido.
- O identificador da nota precisa usar `NFe` seguido de uma chave de 44 posições.
- O número `nNF` deve ser válido e corresponder à chave.
- `dhEmi` é lido como data/hora ISO completa; `dEmi` continua aceito para documentos com data simples. Horas e datas inválidas são rejeitadas. A comparação usa o dia declarado no XML, sem converter para UTC e deslocar a nota para outro dia.
- A emissão precisa estar dentro do intervalo solicitado.
- Quando presente, o protocolo deve referenciar a mesma chave da nota.
- Eventos são associados pelo CNPJ e modelo da chave. O autor do evento pode ser um destinatário ou outro participante, e sua ocorrência pode ser posterior ao período de emissão das notas.
- Permanecem as proteções de tamanho, ZIP, XML sem DTD ou entidades externas e rejeição de namespaces estrangeiros.

O ambiente informado no próprio XML continua conferido como dado do documento. Isso não reintroduz seleção de produção/homologação na interface ou na configuração da consulta.

## Formatos de exportação observados

Foram encontrados XML nos ZIPs disponíveis em `D:\sefaz-data`: documentos padrão, invólucros `nfeProc`/`procEventoNFe` sem namespace com conteúdo fiscal qualificado e um XML de NF-e totalmente sem namespace. Os CNPJ dos emitentes das notas inspecionadas já estavam nas 14 posições canônicas, diferentemente do TXT com pontuação.

A leitura reconhece os elementos fiscais nesses três formatos, mantendo o original byte a byte. A estrutura precisa continuar identificável e as mesmas conferências de identidade, modelo e conteúdo permanecem obrigatórias. Duplicidade do elemento principal ou namespace estrangeiro é rejeitada.

Casos sem namespace padrão recebem `namespace_status` nos metadados e o aviso `nonstandard_xml_namespace` no arquivo ZIP publicado. O detalhe do pedido informa a estrutura de exportação não padronizada.

## Limite da conferência

Esta revisão não implementa validação completa de XSD nem verificação criptográfica da assinatura digital. O estado permanece `pending_schema`, inclusive quando as conferências de identidade passam. Um arquivo sem namespace não é apresentado como aprovado no XSD; seu original é preservado e a condição fica sinalizada.

A inspeção das amostras foi somente leitura, diretamente dos ZIPs e sem acesso à SEFAZ. Usou o CNPJ consistente de cada conjunto, o modelo das chaves e uma janela ampla para verificar compatibilidade do leitor. Isso não substitui a comparação com o CNPJ, modelo e período do pedido real, exercitada também nos testes negativos.

Um dos pacotes de referência contém XML e TXT juntos. A inspeção considerou seus XML individualmente; não classificou esse pacote misto como um ZIP de entrega exclusivo de XML. A publicação continua conferindo o formato pedido.

## Resultado

Os 7.825 XML disponíveis passaram pelas conferências de estrutura e identidade após os ajustes:

| Modelo | Notas | Eventos | Total |
| --- | ---: | ---: | ---: |
| NF-e (55) | 39 | 16 | 55 |
| NFC-e (65) | 7.711 | 59 | 7.770 |

Foram sinalizados 72 XML com namespace não padronizado: 71 com invólucro sem namespace e conteúdo qualificado, e um documento totalmente sem namespace. Não houve regravação dos arquivos do cliente nem envio de nova consulta.

A suíte específica contém 74 casos de XML, incluindo modelos 55/65 e as três formas de exportação. A regressão geral passou com 246 testes no SQLite (um teste de locks ignorado) e 247 no PostgreSQL descartável. Os testes negativos confirmam rejeição de outro CNPJ/modelo, número incoerente, data/hora inválida, emissão fora do intervalo, protocolo incompatível e namespace estrangeiro.
