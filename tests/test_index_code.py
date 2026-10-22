from stock_ops.data.baostock_provider import bs_code_of


def test_bs_code_of():
    assert bs_code_of("600519") == ("600519", "sh.600519")
    assert bs_code_of("sz000001") == ("000001", "sz.000001")
    assert bs_code_of("sh.000300") == ("sh.000300", "sh.000300")
    assert bs_code_of("SZ.399006") == ("sz.399006", "sz.399006")
