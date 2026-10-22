from stock_ops.data.tencent_provider import parse_quote_line

# 按腾讯字段布局构造一行：索引 1 名称、2 代码、3 价、32 涨跌幅、37 成交额(万)、38 换手、39 PE、44 总市值(亿)、45 流通市值(亿)、46 PB
_fields = [""] * 60
_fields[1], _fields[2], _fields[3], _fields[6] = "贵州茅台", "600519", "1312.04", "17490"
_fields[32], _fields[37], _fields[38], _fields[39] = "0.18", "229500", "0.14", "21.5"
_fields[44], _fields[45], _fields[46] = "16482", "16482", "7.9"
LINE = 'v_sh600519="' + "~".join(_fields) + '";'


def test_parse_quote_line():
    d = parse_quote_line(LINE)
    assert d["code"] == "600519" and d["name"] == "贵州茅台"
    assert d["price"] == 1312.04 and d["pe_ttm"] == 21.5 and d["pb"] == 7.9
    assert d["total_mv"] == 16482e8 and d["volume"] == 1749000 and d["amount"] == 229500e4


def test_parse_rejects_short_line():
    assert parse_quote_line('v_sh600519="1~a~b";') is None
    assert parse_quote_line("garbage") is None


def test_default_universe_falls_back(monkeypatch):
    import stock_ops.data.tencent_provider as tp

    def boom():
        raise TimeoutError("sina down")

    monkeypatch.setattr(tp, "sina_universe", boom)
    monkeypatch.setattr(tp, "baostock_universe", lambda: ["000001", "600519"])
    assert tp.default_universe() == ["000001", "600519"]
