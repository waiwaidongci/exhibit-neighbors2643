# 苇谱展陈偏好配对册

用户均值中心化相似邻居协同过滤与留一评分RMSE。为苇谱研究协作组的12位分析与业务人员提供从样本核对、独立worker计算到批准快照交付的完整工作流。

## 真实业务场景

匿名试展显式评分→邻居推荐与冷启动说明→策展备选；仅使用训练评分，相似度共同评分阈值。团队原先将 `exhibit-neighbors-202611-01.csv` 复制到多份人工表格，复核时再逐项对照。三个痛点是口径不可追溯、重复计算易错、业务说明与结果脱节。上游提供合成业务观察，系统承担研究和复核，下游业务人员读取批准快照。全部演示数据是固定随机种子生成的模拟数据。

## 业务模块

1. 业务总览：批次、样本、任务与批准交付账册。
2. 试展评分册：创建/修改来源说明、查看样本、用真实业务字段追加记录；列表分页。
3. 分析配置：冻结来源、参数和全部样本，进入Redis队列。
4. 完整结果：真实算法摘要、专属诊断、全部CSV导出和可恢复失败态。
5. 策展备选：分析师草案→负责人批准→阅读者下载批准快照。
6. 审计：登录、来源修改、任务worker完成、业务说明批准等事件。
7. 留档迁移：不停服把留档迁往新目录，逐份核验内容指纹，页面发起并查看待迁移、迁移中、已完成及阻断原因。

## 快速启动

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
# 可重复执行，不覆盖人工修改
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [前端](http://localhost:18249)；[API文档](http://localhost:19249/docs)。数据库仅演示用途映射 `17749`。首次准备依赖和初始化数据库需要等待健康状态：`docker compose ps`，五个服务均需healthy。

| 组件 | 技术与职责 |
|---|---|
| frontend | 原生 HTML / CSS / JS ES Modules，Nginx代理 `/api/` |
| backend | Python3.11 / FastAPI / SQLAlchemy / JWT |
| worker | 独立Python进程，Redis BLPOP队列，持久化结果/CSV/心跳 |
| db | MySQL8，命名卷持久化 |
| redis | Redis7，AOF命名卷 |

恰好五服务，均配置healthcheck；后端/worker依赖数据库与Redis健康，前端依赖后端健康；worker与后端共享 `artifacts` 命名卷。重置演示环境：`docker compose down -v --remove-orphans`，会删除本项目卷。

## 账号与权限

所有演示账号密码：`Research2026!`。

| 邮箱 | 角色 | 权限 |
|---|---|---|
| admin@exhibit-neighbors.demo | admin | 全部录入/执行、批准业务说明、发起与推进留档迁移 |
| analyst@exhibit-neighbors.demo | analyst | 录入来源/样本、执行、提交说明，无批准权 |
| viewer@exhibit-neighbors.demo | viewer | 只读、导出结果及已批准快照 |

时间在数据库/API中以UTC存储，总览与审计页面明确转换为Asia/Shanghai北京时间。

JWT有效期8小时；PBKDF2盐化哈希保存密码；角色每请求从数据库读取。访客写操作403，匿名访问业务数据401，重复样本409，非法业务字段422，重复批准409。每客户端/路径写请求90次/分钟，超限429。生产使用需修改JWT及演示数据库凭据。

## 实体与字段

Exhibition / VisitorRating / RecommendationRun / CuratorSelection 是核心实体；另有User和Audit。数据库实际表：`exhibitions` → `visitor_ratings` → `recommendation_runs` → `curator_selections`。样本以固定字段JSON保存，后端按以下字段严格验证，不接受未知字段替代必填值：匿名访客（`visitor`）、展品代号（`exhibit`）、评分 1–5（`rating`）。

实体贯穿 `backend/src/models`、`schemas`、`services`、`controllers`、`routes`，以及 `frontend/src/api/research.js`、`stores/research.js` 和 `pages`。`Source.key` 与 `(Record.source_id, reference)` 为自然键；来源改名不会修改已冻结任务输入。业务说明在创建时保存结果快照，批准后从该快照导出。

## 算法与口径

用户均值中心化相似邻居协同过滤与留一评分RMSE，全部计算位于 `backend/src/services/algorithm.py`，前端不拟合模型、不生成模拟结果。输入是冻结业务观察及参数，输出summary、专属诊断、逐行计算明细、seed与输入SHA256。CSV包含全部结果行；页面仅预览前30行。参数：

- `neighbors`：相似邻居上限，默认 `5`。
- `min_common`：共同评分下限，默认 `2`。

访客均值中心化的余弦相似度，仅使用正相似邻居；每位访客留一评分验证，留出评分不进入训练。无邻居时回退展品均值。

失败态：业务字段缺失/非有限数值、参数越界、样本不足、退化特征或结构错误均明确拒绝或将任务标failed，错误消息保存在任务中。可回到来源或配置修正后重新执行，历史失败记录保留。

## 留档迁移

已完成任务的结果CSV与已批准快照CSV登记为留档件（`archive_items`），内容指纹为冻结结果确定性序列化的SHA256；原件口径是数据库中的冻结结果，迁移与修复只序列化冻结结果，**绝不调用算法重算评分冒充原件**。留档根目录为 `ARTIFACT_DIR/archive/gen-N`，生效目录由单行索引（`archive_pointer`）记录。

- 可核验：逐份复制后重读目标文件核对指纹；源文件损坏或缺失时隔离至 `quarantine/` 并按冻结结果重新生成（留修复痕）；冻结结果缺失或与登记指纹不一致的件直接隔离，下载返回409与阻断原因。
- 不停服：迁移期间新任务照常完成并登记进当前生效目录；下载在开始时登记租约绑定当时完整版本，切换后来到的请求走新目录；进行中的下载不受切换影响。
- 断点续传：复制、索引切换、旧件回收分段提交；进程中断后按生效索引校正状态，再执行沿用 `migration_files` 已登记件，已核验份不重复复制。
- 代次围栏：新代登记即取代更旧的未完成代；索引切换是 `generation` 上的原子比较交换，迟归的旧执行者无法回切；同一代的推进用Redis锁互斥，锁不可用时仍由数据库围栏兜底。
- 回收：旧件等到在途下载租约结束（租约10分钟过期兜底）才删除；只删不再被任何登记件引用的旧代文件，worker心跳等共用文件与当前登记位置永不误删。

页面"留档迁移"（负责人发起，其余角色只读）展示生效代次、在途下载、每代进度与阻断原因，以及文件明细（待迁移/迁移中/已完成/已隔离）和留档总账。接口：`GET /archive` 总览；`POST /migrations` 发起新一代并推进；`POST /migrations/{id}/advance` 中断后继续。迁移相关事件（创建、逐代切换、隔离、修复、完成）写入审计。

已知边界：显式1–5评分，不是隐式行为推荐；按展品代码确定性留一，不能当作时间外推验证。相似度只取正值，至少两个共同评分；回退会显示依据。生产建议在完成评估后用全量已知评分，不将训练评分误报验证。

## 演示数据与一天剧本

固定seed=42，3个来源 ` WP-202611-01/02/03`，每来源240条，共720条业务记录；三个账号和首轮种子任务。自然键检查后仅插入缺失数据，连跑seed不重复、不覆盖用户修改。`SEED_DEMO=true` 时启动自动执行；失败记录日志但不阻塞服务。首轮任务同样由独立worker真实计算。

1. 09:00 负责人查看三份来源和720条样本。
2. 09:10 分析师选择 `WP-202611-01 秋季常规组`，核对 `exhibit-neighbors-202611-01.csv`。
3. 09:15 在“试展评分册”核对匿名访客（`visitor`）、展品代号（`exhibit`）、评分 1–5（`rating`），追加编号 `WP-NEW-001` 的样本。
4. 09:20 新建“十一月复核研究”，按默认参数冻结241条输入。
5. 09:21 独立worker消费Redis队列，返回实算结果与输入校验和。
6. 09:25 分析师查看专属诊断及逐行结果，并下载CSV复算。
7. 09:30 提交“十一月业务复核意见”，负责人核对并批准。
8. 09:40 viewer下载批准快照，查看审计中的worker完成与批准事件。
9. 09:50 负责人在“留档迁移”发起新一代迁移：逐份核验指纹后索引切到新目录，viewer下载不受影响；旧件等在途下载结束后回收。

## 目录与本地开发

```text
frontend/src/api, stores, types, components/common, hooks, pages, router, utils, constants
backend/src/routes, controllers, services, models, schemas, middlewares, utils, constants, config
backend/scripts/seed_demo.py
backend/migrations/001_initial.sql, 002_archive.sql
```

本地后端：Python3.11虚拟环境安装 `backend/requirements.txt`，设置 `DATABASE_URL`、`REDIS_URL`、`ARTIFACT_DIR`，在backend目录运行 `uvicorn src.main:app --reload`；另开终端运行 `python -m src.worker`。原生前端无需编译，推荐以Compose Nginx访问，保证 `/api/` 代理。前端为Google Fonts双字体、oklch色板，离线字体回退serif；1280/768/390响应布局。

| 环境变量 | 默认与说明 |
|---|---|
| COMPOSE_PROJECT_NAME | `exhibit-neighbors`，隔离容器/网络/命名卷 |
| FRONTEND_PORT / BACKEND_PORT / DB_PORT | `18249 / 19249 / 17749` |
| SEED_DEMO | `true` |
| JWT_SECRET | `.env.example`演示值，部署前修改 |
| DATABASE_URL / REDIS_URL | Compose内部连接，定义在compose的env锚点 |
| ARTIFACT_DIR | `/artifacts`，后端worker共享 |

共享枚举：`backend/src/constants/enums.py` 与 `frontend/src/constants/enums.js` 都定义 admin/analyst/viewer、queued/running/completed/failed、draft/approved，以及留档迁移的 ready/quarantined、迁移代次与文件状态。后端service检查对应字符串；README为全量值说明。共享前端组件table/status/chart/business跨总览、结果、配置与复核复用；actions hook和format utils负责交互/格式。后端errors与rate_limit是两个中间件。

测试及截图在批根 `test-artifacts/gb-0045/`，不混入源码。独立算法oracle、HTTP完整流程和真实Playwright浏览器流程见该目录 `TESTING.md`。License：MIT。
