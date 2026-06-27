# 09-order-processor — 订单处理器。

> Java + Javalin + JDBC + Jedis。后台生产者每 5s 向 `orders:queue` XADD 订单；消费者 XREADGROUP 拉取后 INSERT 到 `processed_orders` 表并 XACK。

## 基本信息

| 字段 | 值 |
| --- | --- |
| 服务 ID | `09-order-processor` |
| Pod label | `app=order-processor` |
| 镜像 | `vibe/09-order-processor:dev`（`imagePullPolicy: Never`） |
| 语言 / 技术栈 | Java 21 / Javalin 6 |
| 监听端口 | 8080 |
| 依赖 | postgres、redis_stream |
| 适用故障 | `F01-pod-kill`, `F02-network-delay`, `F05-db-down`, `F06-db-slow`, `F09-queue-down`, `F10-queue-slow` |
| 健康检查 | `GET /healthz` |

## 端点

```
GET /healthz
GET /stats               consumed / errors 计数
```

## 行为约定

Stream 或 Postgres 故障时 errors 计数增加并打印 `ERROR ...`。

---

## 如何运行

每个服务下都有一个 `run.sh`，下面是常用子命令（在仓库根目录执行）：

```bash
# 1) 构建镜像并 kind load 进 'vibe' 集群
bash services/09-order-processor/run.sh build

# 2) 应用 k8s 清单
bash services/09-order-processor/run.sh deploy

# 3) 等待 rollout 就绪
bash services/09-order-processor/run.sh wait

# 4) 烟囱测试（默认 curl /healthz）
bash services/09-order-processor/run.sh smoke
```

也可以用 Makefile 一行：

```bash
make build  SVC=09-order-processor
make deploy SVC=09-order-processor
make wait   SVC=09-order-processor
make smoke  SVC=09-order-processor
```

## 如何注射故障

本服务支持的故障：

| ID | 窗口 | 说明 |
| --- | --- | --- |
| `F01-pod-kill` | 60s | 杀掉本服务的 pod（PodChaos one-shot） |
| `F02-network-delay` | 120s | 对本服务注入 500ms ± 100ms 网络延迟（NetworkChaos） |
| `F05-db-down` | 60s | 杀掉 postgres pod |
| `F06-db-slow` | 120s | 对 postgres pod 注入网络延迟 |
| `F09-queue-down` | 60s | 杀掉 redis-stream pod |
| `F10-queue-slow` | 120s | 对 redis-stream 注入网络延迟 |

可用命令（每条独立注射，会在 `runs/09-order-processor/<时间戳>/<故障>/` 目录下生成 `meta.json` 等元数据）：

```bash
bash services/09-order-processor/run.sh inject F01-pod-kill
bash services/09-order-processor/run.sh inject F02-network-delay
bash services/09-order-processor/run.sh inject F05-db-down
bash services/09-order-processor/run.sh inject F06-db-slow
bash services/09-order-processor/run.sh inject F09-queue-down
bash services/09-order-processor/run.sh inject F10-queue-slow
```

注射期间，框架会自动启动一个针对本服务的端口转发，并按 1Hz 反复调用 `services/09-order-processor/exercise.sh` 中的 `exercise_once()`，向服务发送真实流量，从而让被故障打中的代码路径在日志中暴露错误信号。

## 如何检测

判定逻辑是 **故障注射后的日志窗口分析**：判官读取本服务在故障注射时段（`t_start ~ t_end`）的 pod 日志，并按 `judge/oracle.yaml` 中的正则去匹配。匹配成功 → `caught=true`。

判定命令：

```bash
# 对最新一次注射结果做判定（顶层目录或单个 fault 目录都支持）
bash services/09-order-processor/run.sh judge

# 或者直接调判官
python3 judge/judge.py runs/09-order-processor/<时间戳>/
```

输出：每个 fault 子目录写入 `verdict.json`，顶层目录写入 `summary.json`，控制台打印 `caught N/M` 汇总。

## 一键演示

```bash
make demo SVC=09-order-processor
# 等价于：build + deploy + wait + smoke + (inject 所有适用故障) + judge
```

完成后查看：

```bash
ls runs/09-order-processor/
cat runs/09-order-processor/<最新时间戳>/summary.json
```
