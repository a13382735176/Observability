# 14-metrics-aggregator — 指标聚合器。

> Python + FastAPI + redis.asyncio。后台生产者每 1s 向 `metrics:queue` XADD 4 种指标轮流；消费者 INCRBY 计数器 `counter:<metric>`。

## 基本信息

| 字段 | 值 |
| --- | --- |
| 服务 ID | `14-metrics-aggregator` |
| Pod label | `app=metrics-aggregator` |
| 镜像 | `vibe/14-metrics-aggregator:dev`（`imagePullPolicy: Never`） |
| 语言 / 技术栈 | Python 3.12 / FastAPI |
| 监听端口 | 8080 |
| 依赖 | redis_cache、redis_stream |
| 适用故障 | `F01-pod-kill`, `F02-network-delay`, `F07-cache-down`, `F08-cache-slow`, `F09-queue-down`, `F10-queue-slow` |
| 健康检查 | `GET /healthz` |

## 端点

```
GET /healthz
GET /metrics              Prometheus 风格文本输出当前计数器
```

## 行为约定

队列或 cache 故障在 consumer/producer loop 中打印 `ERROR ...` 并增加 errors 计数。

---

## 如何运行

每个服务下都有一个 `run.sh`，下面是常用子命令（在仓库根目录执行）：

```bash
# 1) 构建镜像并 kind load 进 'vibe' 集群
bash services/14-metrics-aggregator/run.sh build

# 2) 应用 k8s 清单
bash services/14-metrics-aggregator/run.sh deploy

# 3) 等待 rollout 就绪
bash services/14-metrics-aggregator/run.sh wait

# 4) 烟囱测试（默认 curl /metrics）
bash services/14-metrics-aggregator/run.sh smoke
```

也可以用 Makefile 一行：

```bash
make build  SVC=14-metrics-aggregator
make deploy SVC=14-metrics-aggregator
make wait   SVC=14-metrics-aggregator
make smoke  SVC=14-metrics-aggregator
```

## 如何注射故障

本服务支持的故障：

| ID | 窗口 | 说明 |
| --- | --- | --- |
| `F01-pod-kill` | 60s | 杀掉本服务的 pod（PodChaos one-shot） |
| `F02-network-delay` | 120s | 对本服务注入 500ms ± 100ms 网络延迟（NetworkChaos） |
| `F07-cache-down` | 60s | 杀掉 redis-cache pod |
| `F08-cache-slow` | 120s | 对 redis-cache 注入网络延迟 |
| `F09-queue-down` | 60s | 杀掉 redis-stream pod |
| `F10-queue-slow` | 120s | 对 redis-stream 注入网络延迟 |

可用命令（每条独立注射，会在 `runs/14-metrics-aggregator/<时间戳>/<故障>/` 目录下生成 `meta.json` 等元数据）：

```bash
bash services/14-metrics-aggregator/run.sh inject F01-pod-kill
bash services/14-metrics-aggregator/run.sh inject F02-network-delay
bash services/14-metrics-aggregator/run.sh inject F07-cache-down
bash services/14-metrics-aggregator/run.sh inject F08-cache-slow
bash services/14-metrics-aggregator/run.sh inject F09-queue-down
bash services/14-metrics-aggregator/run.sh inject F10-queue-slow
```

注射期间，框架会自动启动一个针对本服务的端口转发，并按 1Hz 反复调用 `services/14-metrics-aggregator/exercise.sh` 中的 `exercise_once()`，向服务发送真实流量，从而让被故障打中的代码路径在日志中暴露错误信号。

## 如何检测

判定逻辑是 **故障注射后的日志窗口分析**：判官读取本服务在故障注射时段（`t_start ~ t_end`）的 pod 日志，并按 `judge/oracle.yaml` 中的正则去匹配。匹配成功 → `caught=true`。

判定命令：

```bash
# 对最新一次注射结果做判定（顶层目录或单个 fault 目录都支持）
bash services/14-metrics-aggregator/run.sh judge

# 或者直接调判官
python3 judge/judge.py runs/14-metrics-aggregator/<时间戳>/
```

输出：每个 fault 子目录写入 `verdict.json`，顶层目录写入 `summary.json`，控制台打印 `caught N/M` 汇总。

## 一键演示

```bash
make demo SVC=14-metrics-aggregator
# 等价于：build + deploy + wait + smoke + (inject 所有适用故障) + judge
```

完成后查看：

```bash
ls runs/14-metrics-aggregator/
cat runs/14-metrics-aggregator/<最新时间戳>/summary.json
```
