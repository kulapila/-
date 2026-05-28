# Survey Pipeline: Code Generation Research

自动化综述生成系统，持续跟踪 Code Generation 方向的 arXiv 论文，通过 DeepSeek API 进行结构化分析、聚类分类，生成每周更新的综述摘要。

## 核心功能

- **自动抓取论文**: arXiv API 抓取近 1-2 年 Code Generation 领域论文
- **结构化分析**: DeepSeek 生成每篇论文的 11 字段结构化卡片
- **聚类分类**: sentence-transformers 嵌入 + HDBSCAN 聚类，自动构建研究方向分类体系
- **方法对比表**: 方法、复杂度、场景、优缺点、是否数据驱动
- **周综述生成**: 每周自动生成 1-2 页综述摘要（分类体系 + 趋势分析 + 研究空白）
- **最终报告**: 整合多周内容生成 6-10 页最终综述报告
- **完全自动化**: GitHub Actions 每周一自动运行

## 快速开始

### 1. 环境准备

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY
```

DeepSeek API Key 获取: https://platform.deepseek.com/

### 3. 运行

```bash
# 一键运行全流程
python -m src.pipeline --full

# 单独运行某个模块
python -m src.pipeline --step fetcher    # 抓取论文
python -m src.pipeline --step cards      # 生成论文卡片
python -m src.pipeline --step cluster    # 聚类分类
python -m src.pipeline --step compare    # 方法对比表
python -m src.pipeline --step digest     # 生成周综述
python -m src.pipeline --step report     # 生成最终报告

# 增量更新
python -m src.pipeline --incremental
```

## 配置说明

编辑 `config.yaml` 调整：

- `api.deepseek.model_cards` — 论文分析模型（默认 `deepseek-chat`）
- `arxiv.search_query` — arXiv 搜索关键词
- `arxiv.date_range_years` — 搜索时间范围
- `clustering.min_cluster_size` — 最小聚类大小

## 输出文件

| 文件 | 说明 |
|------|------|
| `data/papers_raw.json` | 原始论文数据 |
| `data/paper_cards.jsonl` | 结构化论文卡片 |
| `data/taxonomy.md` | 研究分类体系 |
| `data/comparison_table.csv` | 方法对比表 |
| `data/weekly/digest_*.md` | 每周综述 |
| `output/final_report.md` | 最终综述报告 |

## GitHub Actions

在 GitHub 仓库 Settings → Secrets 中添加 `DEEPSEEK_API_KEY`，workflow 会每周一自动运行。

## 项目结构

```
survey_pipeline/
├── config.yaml                  # 配置文件
├── src/
│   ├── models.py               # 数据模型
│   ├── config.py               # 配置管理
│   ├── utils.py                # 工具函数
│   ├── rate_limiter.py         # 速率限制
│   ├── fetcher.py              # arXiv 抓取
│   ├── paper_card.py           # 论文卡片生成
│   ├── clustering.py           # 聚类分类
│   ├── comparison.py           # 方法对比表
│   ├── digest.py               # 周综述生成
│   ├── report.py               # 最终报告
│   └── pipeline.py             # 总调度器
├── data/                        # 数据输出
└── output/                      # 报告输出
```
