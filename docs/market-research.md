# 市场调研：A 股个人分析系统的数据源与设计依据

调研日期：2026-10-22

## 1. 免费数据源对比

| 数据源 | 覆盖范围 | 稳定性 | 限制 | 适用场景 |
|---|---|---|---|---|
| **AKShare** | 最广：实时行情、日K、财务指标、资金流、板块、龙虎榜 | 弱。本质是爬虫聚合，目标站改版或反爬后接口失效，社区通常数天内修复 | 东方财富接口高频调用会被封 IP；社区实测约每 IP 每分钟 60 次（非官方数字） | 广度数据、基本面快照、补充数据 |
| **Baostock** | A 股日K（可追溯到 1990 年）、分钟线近 5 年、除权因子、部分估值字段（peTTM、pbMRQ） | 强。官方服务器直连，不依赖爬虫 | 无 Token；社区对是否限流说法不一，实践中加短暂休眠即可 | 历史 K 线主来源、回测 |
| **Tushare Pro** | 基本面数据最规范，龙虎榜、北向资金是特色 | 中 | 积分制，免费版实时数据延迟 15 分钟，很多接口需 2000+ 积分 | 本项目不作为依赖，留作可选接入 |
| 腾讯 / 新浪行情接口 | 实时报价 | 中 | 非官方 API，随时可能变 | AKShare 内部已封装为 `stock_zh_a_hist_tx` 等，作为东财备用 |

### AKShare 东方财富接口近期故障记录（GitHub Issues）

| Issue | 日期 | 现象 |
|---|---|---|
| #7402 | 2026-08 | `stock_zh_a_hist()` 无法获取历史行情 |
| #7208 | 2026-04 | 部分 `_em` 接口请求不通 |
| #7166 | 2026-03 | `stock_zh_a_spot_em` 报 RemoteDisconnected |
| #7051 | 2026-02 | `stock_zh_a_hist` 和 `stock_individual_info_em` 不可用 |
| #7005 | 2026-01 | 服务器部署环境被识别并断开连接 |
| #6100 | 2025-04 | 43 条评论，集中讨论东财接口失败原因与修复 |

结论：东方财富接口平均每 1 到 2 个月出一次故障，必须有备用源。

## 2. 数据源决策

1. **历史日K 主源用 Baostock**，备源用 AKShare 的腾讯接口 `stock_zh_a_hist_tx`，再备 AKShare 东财接口。
2. **全市场快照（PE、PB、市值、换手）用 AKShare `stock_zh_a_spot_em`**，失败时退化为 Baostock 的 peTTM / pbMRQ 字段逐只拼接。
3. **所有数据本地缓存到 SQLite**，增量更新，分析和回测只读缓存，不在分析时发网络请求。
4. 请求之间加固定间隔和指数退避重试，避免被封。

## 3. 同类开源项目借鉴

| 项目 | 可借鉴点 | 不采用的部分 |
|---|---|---|
| [Sequoia](https://github.com/sngyai/Sequoia) | Baostock 作为唯一数据源，SQLite 本地存储，日更增量 + 一次性全量回填两种模式，crontab 盘后运行 | 策略偏短线形态，无持仓管理 |
| [KHunter](https://github.com/ling-0729/KHunter) | 策略注册表模式，风控规则（剔除 ST、退市、微小市值、近期大涨股；按大盘 ADX 控制仓位上限），配置 YAML 化 | Flask Web UI 过重，依赖 AKShare 单源 |
| [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) | **用 GitHub Actions 定时运行，零成本无需服务器**，工作日 18:00 北京时间自动跑，非交易日跳过 | LLM 分析和多渠道推送在第一阶段不需要 |
| [go-stock](https://github.com/arvinlovegood/go-stock) | 数据全部本地保留的理念 | Go 语言，与本项目技术栈不同 |
| [qstock](https://github.com/tkfy920/qstock) | RPS、MM 趋势等选股模型 | 5 年未更新 |

共同的空白：这些项目都没有完整的**持仓与交易记录管理**，这是本项目要补的核心功能。

## 4. 分析方法选择

对个人投资者实用的流程，来自多篇量化筛选指南的共识：

1. **基本面硬过滤**：估值（PE、PB）、盈利质量（ROE、净利润增速）、市值下限、剔除 ST 和上市不足一年的新股。
2. **技术面排序**：均线多头、MACD、RSI、布林带、成交量放大、20 日新高等信号。
3. **风险处理**：行业中性与缩尾处理，把换手率和交易成本计入回测，动量不当作未来收益预测。
4. 任何胜率或收益宣称都只是历史回测，不代表未来。

## 5. 实测：数据中心 IP 下各接口可用性（GitHub Actions，2026-10-22）

| 接口 | GitHub Actions（美国数据中心） | 家庭宽带（预期） |
|---|---|---|
| Baostock 日K / 股票列表 | 可用 | 可用 |
| 新浪全市场行情 `ak.stock_zh_a_spot()` | 可用，5576 只 | 可用 |
| 腾讯批量行情 `qt.gtimg.cn` | 可用，含 PE / PB / 总市值 / 换手 | 可用 |
| 东方财富 `stock_zh_a_hist` / `stock_zh_a_spot_em` | **被拒绝**（RemoteDisconnected，对应 akshare #7005） | 通常可用 |
| 腾讯历史K `stock_zh_a_hist_tx` | 不稳定（ConnectionError / 解析错误） | 可用 |

由此确定的兜底顺序：

- 日K：Baostock → 腾讯历史K → 东财
- 快照：东财（快）→ 腾讯批量（数据中心可用）→ Baostock 逐只（最慢最稳，无市值字段）

## 6. 运行环境

| 环境 | 用途 | 说明 |
|---|---|---|
| 本地电脑 | 日常使用 CLI | 需要 Python 3.10+ |
| GitHub Actions | 自动化测试与定时数据更新 | 托管服务器有完整外网，akshare / baostock 均可用。公开仓库分钟数不限，私有仓库每月 2000 分钟免费 |
| Claude Code 云容器 | 代码编写 | 网络策略拦截国内金融站点，无法直接拉数据，通过 Actions 验证 |

## 参考来源

- [AKShare vs Tushare vs Baostock 对比](https://zhuanlan.zhihu.com/p/2067012476840031953)
- [2026 主流股票数据 API 对比测评](https://zhuanlan.zhihu.com/p/2046889608231786018)
- [A 股量化数据接口怎么选](https://developer.cloud.tencent.com/article/2738002)
- [AKShare GitHub Issues](https://github.com/akfamily/akshare/issues)
- [KHunter](https://github.com/ling-0729/KHunter)、[Sequoia](https://github.com/sngyai/Sequoia)、[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)、[go-stock](https://github.com/arvinlovegood/go-stock)、[qstock](https://github.com/tkfy920/qstock)
