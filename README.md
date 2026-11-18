# 槐序干燥时长试算台

RandomForest回归、训练内特征子集交叉验证与留出集MAE。为槐序研究协作组的12位分析与业务人员提供从样本核对、独立worker计算到批准快照交付的完整工作流。

## 真实业务场景

物料初始湿度/厚度/温度→干燥时长估计→工艺试验备忘；解释用留出置换重要性，禁止用留出集选参。团队原先将 `drying-forest-202611-01.csv` 复制到多份人工表格，复核时再逐项对照。三个痛点是口径不可追溯、重复计算易错、业务说明与结果脱节。上游提供合成业务观察，系统承担研究和复核，下游业务人员读取批准快照。全部演示数据是固定随机种子生成的模拟数据。

## 业务模块

1. 业务总览：批次、样本、任务、配对对照与批准交付账册。
2. 干燥研究：创建/修改来源说明、查看样本、用真实业务字段追加记录；列表分页。
3. 分析配置：冻结来源、参数和全部样本，进入Redis队列。
4. 完整结果：真实算法摘要、专属诊断、全部CSV导出和可恢复失败态。
5. 配对对照：两种工艺分别受理两组来料，冻结样本与湿度/厚度容差，容差内一对一配对后估计配对时长差及区间；未见完整配对名单与区间不开放查看和下载。
6. 工艺试验备忘：分析师草案→负责人批准→阅读者下载批准快照。
7. 审计：登录、来源修改、任务worker完成、业务说明批准等事件。

## 快速启动

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
# 可重复执行，不覆盖人工修改
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [前端](http://localhost:18248)；[API文档](http://localhost:19248/docs)。数据库仅演示用途映射 `17748`。首次准备依赖和初始化数据库需要等待健康状态：`docker compose ps`，五个服务均需healthy。

| 组件 | 技术与职责 |
|---|---|
| frontend | 原生 HTML / CSS / JS ES Modules，Nginx代理 `/api/` |
| backend | Python3.11 / FastAPI / SQLAlchemy / JWT |
| worker | 独立Python进程，Redis BLPOP队列，持久化结果/CSV/心跳 |
| db | PostgreSQL16，命名卷持久化 |
| redis | Redis7，AOF命名卷 |

恰好五服务，均配置healthcheck；后端/worker依赖数据库与Redis健康，前端依赖后端健康；worker与后端共享 `artifacts` 命名卷。重置演示环境：`docker compose down -v --remove-orphans`，会删除本项目卷。

## 账号与权限

所有演示账号密码：`Research2026!`。

| 邮箱 | 角色 | 权限 |
|---|---|---|
| admin@drying-forest.demo | admin | 全部录入/执行、批准业务说明 |
| analyst@drying-forest.demo | analyst | 录入来源/样本、执行、提交说明，无批准权 |
| viewer@drying-forest.demo | viewer | 只读、导出结果及已批准快照 |

时间在数据库/API中以UTC存储，总览与审计页面明确转换为Asia/Shanghai北京时间。

JWT有效期8小时；PBKDF2盐化哈希保存密码；角色每请求从数据库读取。访客写操作403，匿名访问业务数据401，重复样本409，非法业务字段422，重复批准409。每客户端/路径写请求90次/分钟，超限429。生产使用需修改JWT及演示数据库凭据。

## 实体与字段

DryingStudy / DryingSample / RegressionRun / ProcessMemo / PairedComparison 是核心实体；另有User和Audit。数据库实际表：`drying_studies` → `drying_samples` → `regression_runs` → `process_memos`，以及独立的 `paired_comparisons`。样本以固定字段JSON保存，后端按以下字段严格验证，不接受未知字段替代必填值：初始湿度 %（`moisture`）、厚度 mm（`thickness`）、设定温度 ℃（`temperature`）、风量 m³/min（`airflow`）、实测时长 min（`minutes`）。

配对对照（`paired_comparisons`）不属于原时长研究的分支，也不改写它。受理时一次读取两组来源的试件，连同湿度容差、厚度容差和两组标签写入冻结快照与SHA256校验和；之后的补录不会进入本次对照，原时长研究仍按原口径使用样本。

实体贯穿 `backend/src/models`、`schemas`、`services`、`controllers`、`routes`，以及 `frontend/src/api/research.js`、`stores/research.js` 和 `pages`。`Source.key` 与 `(Record.source_id, reference)` 为自然键；来源改名不会修改已冻结任务输入。业务说明在创建时保存结果快照，批准后从该快照导出。

## 算法与口径

RandomForest回归、训练内特征子集交叉验证与留出集MAE，全部计算位于 `backend/src/services/algorithm.py`，前端不拟合模型、不生成模拟结果。输入是冻结业务观察及参数，输出summary、专属诊断、逐行计算明细、seed与输入SHA256。CSV包含全部结果行；页面仅预览前30行。参数：

- `trees`：森林树数，默认 `60`。
- `depth`：最大深度，默认 `6`。

先固定留出集，特征选择与交叉验证仅在训练行完成；留出集只作最后一次评估。置换重要性是模型依赖度，不是因果贡献。

失败态：业务字段缺失/非有限数值、参数越界、样本不足、退化特征或结构错误均明确拒绝或将任务标failed，错误消息保存在任务中。可回到来源或配置修正后重新执行，历史失败记录保留。

已知边界：只比较三个预定义特征子集，超参数由分析前固定；留出集不用于选择。置换重要性来自最后留出集，不可反复依据它改模再宣称独立验证。不含预测区间，不用于外推工艺。

### 配对对照口径

两种干燥工艺接到的来料不同，直接比较各自平均时长会把来料差异算进工艺差异，因此采用配对对照：

- 两组来自不同来源，受理时在不同任务的同一受理动作里冻结，不混用两个截点；同一来源不能既当A组又当B组。
- 规模上限：每组最多1000件；湿度容差(0,100]、厚度容差(0,1000] mm；容差内候选超过60000对时要求收紧容差，避免无界计算。
- 选对只读取初始湿度与厚度，实测时长不进入候选、代价、排序或任何选对分支。每件试件最多配对一次。
- 目标按字典序：合格配对数最多 → 按 `|湿度差|/湿度容差 + |厚度差|/厚度容差` 折算的总差最小 → 总差同分时按两组样本编号升序取字典序最小的名单。求解用整数化代价的全局指派，不用贪心逐步就近。
- 未配成的试件逐条保留：容差内无候选，或容差内候选均已被更优配对占用，并记录候选数。
- 差值定义为 A组实测时长 − B组实测时长；用配对差值的单样本t区间（95%，n−1自由度）估计平均差，不用两组独立均值比较；有效配对少于2对时任务失败并说明原因。
- 页面与两个CSV（配对明细、未配对原因）只在配对名单与区间都齐全后开放；未完成、失败的对照不返回配对、区间或明细行。
- worker 先落盘配对名单再估计区间；若在名单保存后中断，重试沿用原冻结样本和原名单，不重新选对；重复队列消息或并发重试不会二次发布，发布时间只写一次。

## 演示数据与一天剧本

固定seed=42，3个来源 ` HX-202611-01/02/03`，每来源240条，共720条业务记录；三个账号、首轮种子任务和一条“首轮工艺配对对照”（来源01与02，湿度容差3%、厚度容差0.8mm）。自然键检查后仅插入缺失数据，连跑seed不重复、不覆盖用户修改。`SEED_DEMO=true` 时启动自动执行；失败记录日志但不阻塞服务。首轮任务与配对对照同样由独立worker真实计算。

1. 09:00 负责人查看三份来源和720条样本。
2. 09:10 分析师选择 `HX-202611-01 秋季常规组`，核对 `drying-forest-202611-01.csv`。
3. 09:15 在“干燥研究”核对初始湿度 %（`moisture`）、厚度 mm（`thickness`）、设定温度 ℃（`temperature`）、风量 m³/min（`airflow`）、实测时长 min（`minutes`），追加编号 `HX-NEW-001` 的样本。
4. 09:20 新建“十一月复核研究”，按默认参数冻结241条输入。
5. 09:21 独立worker消费Redis队列，返回实算结果与输入校验和。
6. 09:25 分析师查看专属诊断及逐行结果，并下载CSV复算。
7. 09:30 提交“十一月业务复核意见”，负责人核对并批准。
8. 09:40 viewer下载批准快照，查看审计中的worker完成与批准事件。
9. 09:50 分析师在“配对对照”以 `HX-202611-01` 为A组、`HX-202611-02` 为B组受理，冻结湿度容差3%、厚度容差0.8mm；worker先保存配对名单，再给出配对时长差的平均差与95%区间，未配成试件附原因。
10. 09:55 分析师对同一对照点击重试模拟中断恢复：沿用原冻结样本，若名单已保存则直接估计区间；已发布的对照拒绝重复执行，发布时间不变。

## 目录与本地开发

```text
frontend/src/api, stores, types, components/common, hooks, pages, router, utils, constants
backend/src/routes, controllers, services, models, schemas, middlewares, utils, constants, config
backend/scripts/seed_demo.py
backend/migrations/001_initial.sql
```

本地后端：Python3.11虚拟环境安装 `backend/requirements.txt`，设置 `DATABASE_URL`、`REDIS_URL`、`ARTIFACT_DIR`，在backend目录运行 `uvicorn src.main:app --reload`；另开终端运行 `python -m src.worker`。原生前端无需编译，推荐以Compose Nginx访问，保证 `/api/` 代理。前端为Google Fonts双字体、oklch色板，离线字体回退serif；1280/768/390响应布局。

| 环境变量 | 默认与说明 |
|---|---|
| COMPOSE_PROJECT_NAME | `drying-forest`，隔离容器/网络/命名卷 |
| FRONTEND_PORT / BACKEND_PORT / DB_PORT | `18248 / 19248 / 17748` |
| SEED_DEMO | `true` |
| JWT_SECRET | `.env.example`演示值，部署前修改 |
| DATABASE_URL / REDIS_URL | Compose内部连接，定义在compose的env锚点 |
| ARTIFACT_DIR | `/artifacts`，后端worker共享 |

共享枚举：`backend/src/constants/enums.py` 与 `frontend/src/constants/enums.js` 都定义 admin/analyst/viewer、queued/running/estimating/completed/failed、draft/approved。后端service检查对应字符串；README为全量值说明。共享前端组件table/status/chart/business跨总览、结果、配置与复核复用；actions hook和format utils负责交互/格式。后端errors与rate_limit是两个中间件。

测试及截图在批根 `test-artifacts/gb-0044/`，不混入源码。独立算法oracle、HTTP完整流程和真实Playwright浏览器流程见该目录 `TESTING.md`。配对算法的穷举对拍、冻结/断点恢复/发布闸门测试在 `backend/tests/`，运行 `cd backend && python3 -m pytest -q tests`。License：MIT。
