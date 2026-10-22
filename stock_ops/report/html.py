"""静态 HTML 看板。单文件、无外部依赖，可发布到 GitHub Pages / Cloudflare Pages，手机可读。

配色遵循 A 股习惯：涨为红、跌为绿，并始终带正负号与箭头，不单靠颜色传递含义。
"""

from __future__ import annotations

import html
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..config import Config
from ..data import Cache
from .build import ReportData

_CSS = """
:root{--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--line:#2a78d6;
--up:#d03b3b;--down:#0ca30c;--accent:#2a78d6}
@media (prefers-color-scheme:dark){:root{--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--line:#3987e5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:22px;margin:8px 0 2px}h2{font-size:17px;margin:28px 0 10px}
a{color:var(--accent)}.sub{color:var(--muted);font-size:13px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--surface);border:1px solid var(--grid);border-radius:10px;padding:12px 14px}.tile .k{color:var(--muted);font-size:12px}
.tile .v{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}.up{color:var(--up)}.down{color:var(--down)}
.wrap{overflow-x:auto;background:var(--surface);border:1px solid var(--grid);border-radius:10px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;white-space:nowrap}td.wrap-text{white-space:normal;min-width:260px;text-align:left}th,td{padding:8px 10px;border-bottom:1px solid var(--grid);text-align:right}
th:first-child,td:first-child,th.l,td.l{text-align:left}th{color:var(--ink2);font-weight:500;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--surface)}
th.sorted::after{content:" ▾";color:var(--muted)}th.asc::after{content:" ▴"}tr:last-child td{border-bottom:0}
.empty{color:var(--muted);padding:14px}svg.spark{display:block}.ok{color:var(--accent)}.dim{color:var(--muted)}
.btn{display:inline-block;padding:8px 14px;border-radius:8px;background:var(--accent);color:#fff;text-decoration:none;font-size:14px}
footer{color:var(--muted);font-size:12px;margin:36px 0 12px}
"""

_JS = """
document.querySelectorAll('table[data-sortable]').forEach(t=>{
  t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
    const asc=th.classList.contains('sorted')&&!th.classList.contains('asc');
    t.querySelectorAll('th').forEach(h=>h.classList.remove('sorted','asc'));th.classList.add('sorted');if(asc)th.classList.add('asc');
    const rows=[...t.tBodies[0].rows];
    rows.sort((a,b)=>{const x=a.cells[i].dataset.v??a.cells[i].textContent,y=b.cells[i].dataset.v??b.cells[i].textContent;
      const nx=parseFloat(x),ny=parseFloat(y);const c=(isNaN(nx)||isNaN(ny))?x.localeCompare(y,'zh'):nx-ny;return asc?c:-c});
    rows.forEach(r=>t.tBodies[0].appendChild(r));}));});
"""


def _fmt(v, kind: str = "num") -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return '<span class="dim">–</span>'
    if kind == "pct":
        cls = "up" if v > 0 else "down" if v < 0 else ""
        arrow = "▲" if v > 0 else "▼" if v < 0 else ""
        return f'<span class="{cls}">{arrow}{v:+.2f}%</span>'
    if kind == "money":
        cls = "up" if v > 0 else "down" if v < 0 else ""
        return f'<span class="{cls}">{v:+,.0f}</span>'
    if kind == "yi":
        return f"{v / 1e8:,.0f}"
    if kind == "action":
        cls = {"卖出": "down", "买入": "up", "持有": "ok", "观望": "dim"}.get(str(v), "")
        return f'<strong class="{cls}">{html.escape(str(v))}</strong>'
    if kind == "bool":
        return '<span class="ok">✓</span>' if v else '<span class="dim">·</span>'
    if kind == "int":
        return f"{int(v):,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return html.escape(str(v))


def _table(
    df: pd.DataFrame, cols: list[tuple[str, str, str]], empty: str = "无数据", max_rows: int = 200
) -> str:
    """cols: (列名, 标题, 格式)。"""
    if df is None or df.empty:
        return f'<div class="wrap"><div class="empty">{empty}</div></div>'
    cols = [c for c in cols if c[0] in df.columns or c[0] == "_spark"]
    head = "".join(
        f'<th class="{"l" if f in ("text", "spark") else ""}">{t}</th>' for _, t, f in cols
    )
    body = []
    for _, r in df.head(max_rows).iterrows():
        cells = []
        for c, _, f in cols:
            if f == "spark":
                cells.append(f'<td class="l">{r.get("_spark", "")}</td>')
                continue
            v = r[c]
            raw = (
                ""
                if v is None or (isinstance(v, float) and math.isnan(v))
                else (v if isinstance(v, (int, float)) else "")
            )
            cls = ' class="l"' if f == "text" else ""
            if c == "reason":
                cls = ' class="wrap-text"'
            cells.append(f'<td{cls} data-v="{raw}">{_fmt(v, "text" if f == "text" else f)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="wrap"><table data-sortable><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def sparkline(closes: list[float], w: int = 120, h: int = 32) -> str:
    """单序列 60 日收盘折线，2px 线宽，无轴；颜色按区间涨跌。"""
    pts = [c for c in closes if c is not None and not math.isnan(c)]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    xs = [i * (w - 4) / (len(pts) - 1) + 2 for i in range(len(pts))]
    ys = [h - 2 - (p - lo) / span * (h - 4) for p in pts]
    d = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    color = "var(--up)" if pts[-1] >= pts[0] else "var(--down)"
    title = f"{len(pts)}日: {pts[0]:.2f} → {pts[-1]:.2f} ({(pts[-1] / pts[0] - 1) * 100:+.1f}%)"
    return (
        f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{title}">'
        f'<title>{title}</title><polyline fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{d}"/></svg>'
    )


def render_site(rd: ReportData, cache: Cache, cfg: Config, repo: str | None = None) -> str:
    repo = repo or "zjxlink/stock-ops"
    pf, sig, scr = rd.portfolio.copy(), rd.signals.copy(), rd.screened.copy()

    # 持仓
    if not pf.empty:
        total_mv = pf["market_value"].sum(skipna=True)
        unreal = pf["unrealized_pnl"].sum(skipna=True)
        realized = pf["realized_pnl"].sum() + sum(rd.closed_pnl.values())
        cost = (pf["avg_cost"] * pf["shares"]).sum()
        ret = unreal / cost * 100 if cost else float("nan")
    else:
        total_mv = unreal = realized = 0.0
        ret = float("nan")
    tiles = f"""
<div class="tiles">
 <div class="tile"><div class="k">持仓市值</div><div class="v">{total_mv:,.0f}</div></div>
 <div class="tile"><div class="k">浮动盈亏</div><div class="v">{_fmt(unreal, "money")}</div><div class="sub">{_fmt(ret, "pct") if not math.isnan(ret) else ""}</div></div>
 <div class="tile"><div class="k">已实现盈亏</div><div class="v">{_fmt(realized, "money")}</div></div>
 <div class="tile"><div class="k">持仓数</div><div class="v">{len(pf)}</div></div>
</div>"""
    if not pf.empty:
        pf["_spark"] = [sparkline(cache.daily(c)["close"].tail(60).tolist()) for c in pf["code"]]
    pf_html = _table(
        pf,
        [
            ("code", "代码", "text"),
            ("name", "名称", "text"),
            ("_spark", "60日", "spark"),
            ("shares", "股数", "int"),
            ("avg_cost", "成本", "num"),
            ("price", "现价", "num"),
            ("pnl_pct", "盈亏%", "pct"),
            ("unrealized_pnl", "浮盈", "money"),
            ("realized_pnl", "已实现", "money"),
            ("weight_pct", "仓位%", "num"),
        ],
        empty="暂无持仓。点击上方「录入交易」添加。",
    )

    # 信号
    if not sig.empty:
        sig["_spark"] = [sparkline(cache.daily(c)["close"].tail(60).tolist()) for c in sig["code"]]
    sig_html = _table(
        sig,
        [
            ("code", "代码", "text"),
            ("name", "名称", "text"),
            ("_spark", "60日", "spark"),
            ("close", "收盘", "num"),
            ("score", "评分", "int"),
            ("ma_bull", "多头", "bool"),
            ("golden_cross", "金叉", "bool"),
            ("macd_cross_up", "MACD金叉", "bool"),
            ("breakout20", "20日新高", "bool"),
            ("volume_up", "放量", "bool"),
            ("rsi", "RSI", "num"),
            ("vol_ratio", "量比", "num"),
            ("ret20", "20日涨幅", "pct"),
        ],
        empty="自选股数据不足，请等待下一次更新。",
    )

    # 筛选
    scr_note = ""
    if scr is not None and "rejects" in scr.attrs:
        rj = scr.attrs["rejects"]
        scr_note = (
            f'<p class="sub">输入 {scr.attrs.get("input_count", 0)} 只，通过 {len(scr)} 只。剔除：'
            + "，".join(f"{k} {v}" for k, v in rj.items())
            + "。按列标题可排序。</p>"
        )
    scr_html = _table(
        scr,
        [
            ("code", "代码", "text"),
            ("name", "名称", "text"),
            ("price", "现价", "num"),
            ("pct_chg", "涨跌", "pct"),
            ("pe_ttm", "PE", "num"),
            ("pb", "PB", "num"),
            ("total_mv", "市值(亿)", "yi"),
            ("turnover", "换手%", "num"),
            ("roe", "ROE%", "num"),
            ("yoy_ni", "净利同比%", "pct"),
            ("yoy_ni_prev", "上期同比%", "pct"),
            ("liability_to_asset", "负债率%", "num"),
            ("quality", "质量分", "num"),
            ("report_date", "财报期", "text"),
        ],
        empty="尚未获取全市场快照。",
        max_rows=150,
    )

    # 操作计划
    plan_html, plan_note = "", ""
    if rd.plan is not None and not rd.plan.empty:
        plan_note = f'<p class="sub">{html.escape(rd.plan_note)}</p>'
        plan_html = _table(
            rd.plan,
            [
                ("code", "代码", "text"),
                ("name", "名称", "text"),
                ("status", "状态", "text"),
                ("action", "动作", "action"),
                ("order_price", "挂单价", "num"),
                ("shares", "股数", "int"),
                ("stop_price", "成本止损", "num"),
                ("trail_price", "移动止损", "num"),
                ("exit_level", "出场位", "num"),
                ("entry_level", "进场位", "num"),
                ("prediction", "明日预测", "text"),
                ("reason", "说明", "text"),
            ],
        )
    # 持仓与自选基本面
    fund_html, fund_note = "", ""
    if rd.fundamentals is not None and not rd.fundamentals.empty:
        fund_note = f'<p class="sub">{html.escape(rd.fund_note)}</p>'
        fund_html = _table(
            rd.fundamentals,
            [
                ("code", "代码", "text"),
                ("name", "名称", "text"),
                ("report_date", "财报期", "text"),
                ("roe", "ROE%", "num"),
                ("roe_prev", "上期ROE%", "num"),
                ("np_margin", "净利率%", "num"),
                ("gp_margin", "毛利率%", "num"),
                ("yoy_ni", "净利同比%", "pct"),
                ("yoy_ni_prev", "上期同比%", "pct"),
                ("liability_to_asset", "负债率%", "num"),
                ("cfo_to_np", "现金流/净利", "num"),
                ("eps_ttm", "EPS TTM", "num"),
                ("pe_ttm", "PE", "num"),
                ("pb", "PB", "num"),
            ],
        )
    # 预测
    pred_html, pred_note = "", ""
    if rd.predictions is not None and not rd.predictions.empty:
        pr = rd.predictions.copy()
        pr["reliable"] = pr["reliable"].map({True: "可参考", False: "不足"})
        pred_note = f'<p class="sub">{html.escape(rd.prediction_note)}</p>'
        pred_html = _table(
            pr,
            [
                ("code", "代码", "text"),
                ("name", "名称", "text"),
                ("date", "基于收盘", "text"),
                ("reliable", "可靠性", "text"),
                ("method", "方法", "text"),
                ("pred", "明日", "text"),
                ("prob", "概率", "num"),
                ("acc", "准确率%", "num"),
                ("ci_low", "置信下限%", "num"),
                ("baseline", "基线%", "num"),
                ("n", "样本", "int"),
                ("live_n", "真实前瞻", "int"),
            ],
        )
        if rd.accuracy is not None and not rd.accuracy.empty:
            ac = rd.accuracy.copy()
            ac["significant"] = ac["significant"].map({True: "✓", False: "·"})
            pred_html += (
                '<h3 style="font-size:15px;margin:18px 0 8px">各方法准确率（最近窗口，可按列排序）</h3>'
                + _table(
                    ac,
                    [
                        ("code", "代码", "text"),
                        ("method", "方法", "text"),
                        ("n", "样本", "int"),
                        ("acc", "准确率%", "num"),
                        ("ci_low", "置信下限%", "num"),
                        ("baseline", "基线%", "num"),
                        ("significant", "显著", "text"),
                        ("live_n", "真实前瞻", "int"),
                        ("live_acc", "前瞻准确率%", "num"),
                    ],
                    max_rows=100,
                )
            )
    # 回测
    bt_html, bt_note = "", ""
    if rd.backtest is not None and not rd.backtest.empty:
        bt = rd.backtest.copy()
        curves = rd.equity_curves or {}
        bt["_spark"] = [
            sparkline(curves.get(c, []), w=120, h=28) if c in curves else "" for c in bt["code"]
        ]
        bt_note = f'<p class="sub">{html.escape(rd.backtest_note)}。总收益与买入持有对比，均为历史回测，不代表未来。</p>'
        bt_html = _table(
            bt,
            [
                ("code", "代码", "text"),
                ("name", "名称", "text"),
                ("_spark", "权益曲线", "spark"),
                ("total_return", "总收益%", "pct"),
                ("buy_hold", "买入持有%", "pct"),
                ("excess", "超额%", "pct"),
                ("cagr", "年化%", "num"),
                ("max_drawdown", "最大回撤%", "num"),
                ("sharpe", "夏普", "num"),
                ("trades", "交易次数", "int"),
                ("win_rate", "胜率%", "num"),
                ("profit_factor", "盈亏比", "num"),
                ("avg_days", "平均持有天", "num"),
            ],
        )
    pf_bt_html = ""
    if rd.portfolio_bt:
        m = rd.portfolio_bt
        spark = sparkline(rd.portfolio_equity or [], w=260, h=48)
        pf_bt_html = (
            '<h3 style="font-size:15px;margin:18px 0 8px">组合回测</h3>'
            f'<p class="sub">{html.escape(rd.portfolio_note)}</p>'
            '<div class="tiles">'
            f'<div class="tile"><div class="k">总收益</div><div class="v">{_fmt(m["total_return"], "pct")}</div><div class="sub">等权买入持有 {_fmt(m["buy_hold"], "pct")}</div></div>'
            f'<div class="tile"><div class="k">最大回撤</div><div class="v">{m["max_drawdown"]:.1f}%</div><div class="sub">Calmar {m["calmar"]:.2f}</div></div>'
            f'<div class="tile"><div class="k">年化 / 夏普</div><div class="v">{m["cagr"]:.1f}%</div><div class="sub">夏普 {m["sharpe"]:.2f}</div></div>'
            f'<div class="tile"><div class="k">交易 / 胜率 / 盈亏比</div><div class="v">{m["trades"]}</div><div class="sub">胜率 {m["win_rate"]:.0f}%，盈亏比 {m["profit_factor"]:.2f}</div></div>'
            f'<div class="tile"><div class="k">资金使用率</div><div class="v">{m["exposure"]:.0f}%</div><div class="sub">平均持有 {m["avg_days"]:.0f} 天</div></div>'
            f'<div class="tile"><div class="k">权益曲线</div>{spark}</div>'
            "</div>"
        )
    cmp_html = ""
    if rd.strategy_compare is not None and not rd.strategy_compare.empty:
        cmp_html = (
            '<h3 style="font-size:15px;margin:18px 0 8px">各策略平均表现（同一批股票）</h3>'
            + _table(
                rd.strategy_compare,
                [
                    ("strategy", "策略", "text"),
                    ("description", "规则", "text"),
                    ("total_return", "总收益%", "pct"),
                    ("buy_hold", "买入持有%", "pct"),
                    ("excess", "超额%", "pct"),
                    ("max_drawdown", "最大回撤%", "num"),
                    ("sharpe", "夏普", "num"),
                    ("trades", "交易次数", "num"),
                    ("win_rate", "胜率%", "num"),
                    ("profit_factor", "盈亏比", "num"),
                ],
            )
        )
    gen = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    issue_url = f"https://github.com/{repo}/issues/new?template=trade.yml&title=%E5%BD%95%E5%85%A5%E4%BA%A4%E6%98%93"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>stock-ops 看板</title><style>{_CSS}</style></head><body><main>
<h1>stock-ops 看板 <span class="sub">{html.escape(rd.date)}</span></h1>
<p class="sub">现价：{html.escape(rd.price_note)} · 快照更新：{html.escape(rd.snapshot_updated_at or "无")} · 页面生成：{gen} · <a href="https://github.com/{repo}/tree/main/reports">日报归档</a></p>
<p><a class="btn" href="{issue_url}">录入交易</a> <span class="sub">通过 GitHub Issue 提交，几分钟后自动写入流水并刷新本页。</span></p>
{"<h2>下一交易日操作计划</h2>" + plan_note + plan_html if plan_html else ""}
<h2>持仓</h2>{tiles}{pf_html}
<h2>自选股与持仓股技术信号</h2>{sig_html}
{"<h2>持仓与自选股基本面</h2>" + fund_note + fund_html if fund_html else ""}
<h2>基本面筛选</h2>{scr_note}{scr_html}
{"<h2>明日涨跌预测与准确率</h2>" + pred_note + pred_html if pred_html else ""}
{"<h2>策略回测</h2>" + bt_note + bt_html + pf_bt_html + cmp_html if bt_html else ""}
<footer>数据来源：Baostock、腾讯行情、东方财富。仅供个人研究，不构成投资建议。</footer>
</main><script>{_JS}</script></body></html>"""


def write_site(
    rd: ReportData, cache: Cache, cfg: Config, out_dir: str | Path, repo: str | None = None
) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(render_site(rd, cache, cfg, repo), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return path
