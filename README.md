# stock-ops

个人 A 股分析操作系统。免费数据源、本地 SQLite 缓存、基本面筛选、技术面信号、持仓与交易记录管理，命令行驱动。

## 功能

| 模块 | 说明 |
|---|---|
| 数据 | Baostock 为历史日K主源，AKShare 腾讯 / 东方财富接口自动兜底；全市场快照来自 AKShare。所有数据增量缓存到 SQLite，分析时不发网络请求 |
| 基本面筛选 | 按 PE、PB、市值、换手率硬过滤，自动剔除 ST |
| 技术面信号 | 均线多头、金叉、MACD、RSI、量比、20 日新高、布林收口，综合打分排序 |
| 持仓管理 | 记录买卖流水，移动加权成本，浮盈 / 已实现盈亏 / 仓位占比 |
| 日报 | 一条命令生成 Markdown 日报 |

设计依据见 [docs/market-research.md](docs/market-research.md)。

## 全托管用法（不装任何东西）

| 想做什么 | 怎么做 |
|---|---|
| 看持仓、信号、筛选 | 打开看板 https://zjxlink.github.io/stock-ops/ 。交易时段每 10 分钟刷新实时现价与盈亏，盘后 18:30 更新信号、筛选和日报 |
| 录入一笔交易 | 看板上点「录入交易」，或在仓库 [新建 Issue](https://github.com/zjxlink/stock-ops/issues/new?template=trade.yml) 填表单；也可以直接在 Issue 里写 `buy 600519 1500 100` 这样的文本，每行一笔 |
| 看历史日报 | [reports/](reports/) 目录，每天一份 Markdown |
| 立刻刷新 | Actions 页面手动运行 `Daily report` |
| 改自选股和筛选阈值 | 直接在网页上编辑 [config.yaml](config.yaml) |

录入交易只认仓库所有者发的 Issue，其他人提交会被忽略。流水保存在 [data/trades.csv](data/trades.csv)，可以直接编辑。

## 本地安装（可选）

```bash
git clone https://github.com/zjxlink/stock-ops.git
cd stock-ops
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml                  # 按需修改自选股和筛选阈值
```

## 使用

```bash
stock-ops update                      # 增量更新自选股和持仓股的日K
stock-ops update --snapshot           # 同时拉全市场快照（约 5000 只，用于基本面筛选）
stock-ops update 600519 000858        # 只更新指定代码

stock-ops signals                     # 自选股技术信号排序
stock-ops screen                      # 基本面筛选

stock-ops trade add 600519 buy 1500 100 --date 2026-10-20 --fee 5
stock-ops trade add 600519 sell 1600 50
stock-ops trade list
stock-ops portfolio                   # 持仓与盈亏

stock-ops report                      # 生成 reports/YYYY-MM-DD.md
```

所有命令支持 `-c 其他配置.yaml` 和 `-v` 显示详细日志。

## 开发

```bash
pytest                      # 离线单元测试，不需要网络
ruff check . && ruff format .
python scripts/smoke_live.py   # 真实数据冒烟测试，需要外网
```

GitHub Actions 工作流：

| 工作流 | 触发 | 作用 |
|---|---|---|
| CI | 每次推送 | 单测与 lint |
| Live data smoke | 工作日 18:30 / 手动 | 在 GitHub 服务器上真实访问各数据源，结果写成 commit 评论 |
| Daily report | 工作日 18:30 / 手动 | 更新数据、生成日报和看板、提交并发布到 GitHub Pages |
| Intraday refresh | 交易时段每 10 分钟 / 手动 | 用腾讯实时行情刷新看板现价与盈亏，只发布不提交 |
| Trade entry | 新建 Issue | 解析交易指令写入 trades.csv，回复并关闭 Issue，触发看板刷新 |

## 目录结构

```
stock_ops/
  config.py            配置加载
  data/                数据源抽象、Baostock / AKShare 实现、SQLite 缓存、抓取编排
  analysis/            指标计算、技术信号、基本面筛选
  portfolio/           持仓账本
  report/              日报组装、Markdown 日报、静态 HTML 看板
  cli.py               命令行入口
scripts/daily_job.py   每日盘后任务
scripts/intraday_job.py  盘中实时刷新
scripts/trade_from_issue.py  Issue 录入交易
scripts/smoke_live.py  真实数据冒烟测试
site/                  看板输出（自动生成）
reports/               日报归档（自动生成）
tests/                 离线测试（合成数据）
docs/market-research.md
```

## 免责声明

本项目仅用于个人学习与研究，不构成任何投资建议。所有信号和筛选结果基于历史数据，不代表未来表现。
