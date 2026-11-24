# 数据表初始化

本版通过 `src.models.base.Base.metadata.create_all` 创建首次运行所需的八张表。模型在 `src/models/workflow.py`，其中 `correction_sheets` 与 `correction_records` 承载剪辑组补发的三版计时更正单。早期版本的分析表缺少更正快照列，后端启动时会对 PostgreSQL 执行 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 补齐 `last_sheet_id` 与 `sample`。`python -m scripts.seed_demo` 按观测内容键补全演示样本，保留现有分析及签核。数据库端口只发布到本机。
