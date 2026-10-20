from datetime import date


def test_messages_use_group_ids_and_pagination_not_row_order():
    from apps.fiscal.atf.messages import parse_message_page

    source = b"""<form name="frmMensagens"><table>
    <tr><td>FIS_1322</td><td><a href="javascript:abrirFilhas('20',5)">NF-e</a></td></tr>
    <tr><td>FIS_1322</td><td><a href="javascript:abrirFilhas('10',1)">NF-e</a></td></tr>
    </table><a rel="next"
    href="/atf/seg/SEGf_MinhasMensagens.do?pagina=2">Next</a></form>"""
    page = parse_message_page(source)
    assert [item.id for item in page.items] == ["20", "10"]
    assert page.items[0].children_count == 5
    assert page.next_page == "/atf/seg/SEGf_MinhasMensagens.do?pagina=2"


def test_generic_no_attachment_footer_is_not_empty_result():
    from apps.fiscal.atf.messages import parse_message

    source = """<body>FIS_1322 Período solicitado: 01/10/2024 a 18/10/2024
    Observação: A não existência de arquivo em anexo significa que não existem dados
    para o período consultado.</body>""".encode()
    result = parse_message(source, "21", "20")
    assert result.outcome == "pending"
    assert result.period.start == date(2024, 10, 1)


def test_multiple_attachment_indexes_are_local_to_message():
    from apps.fiscal.atf.messages import parse_message

    source = """<body>FIS_1322 Período solicitado: 01/10/2024 a 18/10/2024
    Tarefa executada com sucesso.
    <a href="javascript:mostrarArquivo(0)">Dados</a>
    <a href="javascript:mostrarArquivo(2)">Dados</a></body>""".encode()
    result = parse_message(source, "21", "20")
    assert [item.index for item in result.attachments] == [0, 2]
    assert all(item.message_id == "21" for item in result.attachments)
    assert result.outcome == "success"
