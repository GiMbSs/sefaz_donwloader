# Consultas com período completo

A implementação anterior dividia NFC-e por dia e NF-e por mês antes do envio à SEFAZ-PB. Essa divisão foi removida: cada modelo envia as datas inicial e final informadas uma vez por formato selecionado.

Um pedido de 01/10 a 20/10 com XML e TXT gera duas consultas, ambas com o intervalo completo. A regra também vale para períodos que atravessam meses ou anos e para downloads automáticos programados.

Pedidos já criados mantêm suas partes e seu histórico. Não há migração de dados nem reenvio automático de consultas já iniciadas. Permanecem as proteções contra envio duplicado, a espera pelos anexos e as novas tentativas persistidas.

Os testes de regressão verificam os dois modelos, XML/TXT, períodos com ano bissexto e mudança de mês/ano, o envio do intervalo ao cliente do portal e a criação de pedidos programados. Esta correção substitui as orientações antigas de divisão diária ou mensal nos planos históricos.
