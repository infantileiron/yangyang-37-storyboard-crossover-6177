# 映格分镜·逐格批注三版随机区组试跑

三种批注模板在同一审修员内随机排序试跑，先看整体秩差，再保护成对模板的多重确认。

## 模拟场景

[业务剧本](yangyang-business.md)记录团队、上游资料、计算口径和交接去向。业务模块包括同人三版试跑、审修员块内计秩、逐组差异与批注模板签核。

观测以 CSV 导入或逐行登记。后台按提交时的观测快照运行 Python 算法；负责人签核后，使用方可查看结果、下载 CSV 或按计划接收报告。

## 计时更正单

剪辑组可补发三版计时更正单（CSV 比观测模板多一列修订号）。更正记录按审修员和修订号合并：迟到的低版不会顶掉已生效的高版，相同内容的重试导入不重复计入。同一审修员最高修订号的计时或试跑次序对不上时，先剔除该审修员，收到无冲突的更高版再纳入。整张更正单在单个事务内生效，并发展开的分析只会取整单生效前或生效后的样本，不会混用。分析提交时固化样本，排队期间收到的更正不影响该次计算；结果的「样本溯源」写清每位审修员采用的修订号以及被剔除的审修员。

## 启动

```sh
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```

浏览器打开 `http://127.0.0.1:18416`。API 健康检查位于 `http://127.0.0.1:19416/api/health`，数据库本地端口 `17916`。停机用 `docker compose down`。只有要重做演示数据时才加 `-v` 清除命名卷。

## 演示账号

| 角色 | 邮箱 | 演示密码 | 可执行动作 |
|---|---|---|---|
| 业务分析员 | `analyst@demo.local` | `Analyst-2026!` | 登记或导入样本、提交分析、下载内部结果 |
| 复核负责人 | `supervisor@demo.local` | `Supervisor-2026!` | 导入资料、签核或退回、安排或停止分发、查审计 |
| 只读查看 | `viewer@demo.local` | `Viewer-2026!` | 查看台账、已签核结果和本地收件箱 |

`.env` 以 `.env.example` 为模板。`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT` 可做本机端口调整。Docker 私有子网可通过 `NETWORK_SUBNET` 覆盖。`JWT_SECRET` 和 `DB_PASSWORD` 为本地演示配置。`SEED_DEMO=false` 可跳过自动种子。所有公开端口绑定在回环地址。首次执行种子后，后续种子只填缺失观测，不覆盖已录入数据。

## 模块和本地开发

| 服务 | 技术 | 用途 |
|---|---|---|
| frontend | HTML、CSS、ES Modules、Nginx | 工作台、录入与报告 |
| backend | Python 3.12、FastAPI、SQLAlchemy | 校验、快照、业务 API 和 JWT |
| worker | Python 3.12、Redis | 计算排队、心跳和到时导出 |
| db | PostgreSQL 16 | 观测、快照、签核、分发计划和审计 |
| redis | Redis 7 | 唤醒、心跳和登录限流 |

在 `backend` 中可用 `pip install -r requirements.txt` 安装本地依赖，设置 `DATABASE_URL`、`REDIS_URL` 和可写 `ARTIFACT_ROOT` 后运行 `uvicorn src.main:app --port 8000`，计算进程运行 `python -m src.worker`。前端修改在 `frontend/src`，用 `docker compose up -d --build frontend` 通过 Nginx 检查同源代理。业务输入定义在 `backend/src/domain/spec.json`，算法在同目录的 `analysis.py`。角色、任务状态和签核状态在后端 `backend/src/constants/enums.py` 和前端 `frontend/src/constants/enums.js` 共同定义。数据库表在 `backend/src/models/workflow.py`。更正单的合并、剔除与样本固化逻辑在 `backend/src/services/corrections.py`，回归测试在 `backend/tests`（设置 `DATABASE_URL` 指向 SQLite 后用 `python -m pytest tests` 运行）。

分发计划锁定特定已签核快照，按北京时间显示。收件箱可下载真实 CSV，当前收件组是本地交接标签。停机跨过多个周期时补送最早未投递的一期，然后追到下一个将来的周期。新快照需重新签核并建新计划。

许可证为 [MIT](LICENSE)。
