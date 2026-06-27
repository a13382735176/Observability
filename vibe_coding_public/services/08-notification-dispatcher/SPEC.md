# 08-notification-dispatcher — 通知调度。

> Python + FastAPI + redis.asyncio + httpx。后台生产者每 2s 向 `notifications:queue` XADD 通知；消费者用 XREADGROUP 拉取，POST 到 mock-upstream `/send`。

## 基本信息

| 字段 | 值 |
| --- | --- |
| 服务 ID | `08-notification-dispatcher` |
| Pod label | `app=notification-dispatcher` |
| 镜像 | `vibe/08-notification-dispatcher:dev`（`imagePullPolicy: Never`） |
| 语言 / 技术栈 | Python 3.12 / FastAPI |
| 监听端口 | 8080 |
| 依赖 | redis_stream、upstream |
| 适用故障 | `F01-pod-kill`, `F02-network-delay`, `F03-upstream-fail`, `F04-upstream-slow`, `F09-queue-down`, `F10-queue-slow` |
| 健康检查 | `GET /healthz` |

## 端点

```
GET /healthz
GET /stats               dispatched / failed 计数
```

## 行为约定

队列或上游故障都会在 stdout 输出 `ERROR ...`，并把 failed 计数加一。

---

## 如何运行

每个服务下都有一个 `run.sh`，下面是常用子命令（在仓库根目录执行）：

```bash
# 1) 构建镜像并 kind load 进 'vibe' 集群
bash services/08-notification-dispatcher/run.sh build

# 2) 应用 k8s 清单
bash services/08-notification-dispatcher/run.sh deploy

# 3) 等待 rollout 就绪
bash services/08-notification-dispatcher/run.sh wait

# 4) 烟囱测试（默认 curl /healthz）
bash services/08-notification-dispatcher/run.sh smoke
```

也可以用 Makefile 一行：

```bash
make build  SVC=08-notification-dispatcher
make deploy SVC=08-notification-dispatcher
make wait   SVC=08-notification-dispatcher
make smoke  SVC=08-notification-dispatcher
```

## 如何注射故障

本服务支持的故障：

| ID | 窗口 | 说明 |
| --- | --- | --- |
| `F01-pod-kill` | 60s | 杀掉本服务的 pod（PodChaos one-shot） |
| `F02-network-delay` | 120s | 对本服务注入 500ms ± 100ms 网络延迟（NetworkChaos） |
| `F03-upstream-fail` | 120s | 让 mock-upstream 返回 500 错误（HTTPChaos Response） |
| `F04-upstream-slow` | 120s | 让 mock-upstream 响应延迟（HTTPChaos Response） |
| `F09-queue-down` | 60s | 杀掉 redis-stream pod |
| `F10-queue-slow` | 120s | 对 redis-stream 注入网络延迟 |

可用命令（每条独立注射，会在 `runs/08-notification-dispatcher/<时间戳>/<故障>/` 目录下生成 `meta.json` 等元数据）：

```bash
bash services/08-notification-dispatcher/run.sh inject F01-pod-kill
bash services/08-notification-dispatcher/run.sh inject F02-network-delay
bash services/08-notification-dispatcher/run.sh inject F03-upstream-fail
bash services/08-notification-dispatcher/run.sh inject F04-upstream-slow
bash services/08-notification-dispatcher/run.sh inject F09-queue-down
bash services/08-notification-dispatcher/run.sh inject F10-queue-slow
```

注射期间，框架会自动启动一个针对本服务的端口转发，并按 1Hz 反复调用 `services/08-notification-dispatcher/exercise.sh` 中的 `exercise_once()`，向服务发送真实流量，从而让被故障打中的代码路径在日志中暴露错误信号。

## 如何检测

判定逻辑是 **故障注射后的日志窗口分析**：判官读取本服务在故障注射时段（`t_start ~ t_end`）的 pod 日志，并按 `judge/oracle.yaml` 中的正则去匹配。匹配成功 → `caught=true`。

判定命令：

```bash
# 对最新一次注射结果做判定（顶层目录或单个 fault 目录都支持）
bash services/08-notification-dispatcher/run.sh judge

# 或者直接调判官
python3 judge/judge.py runs/08-notification-dispatcher/<时间戳>/
```

输出：每个 fault 子目录写入 `verdict.json`，顶层目录写入 `summary.json`，控制台打印 `caught N/M` 汇总。

## 一键演示

```bash
make demo SVC=08-notification-dispatcher
# 等价于：build + deploy + wait + smoke + (inject 所有适用故障) + judge
```

完成后查看：

```bash
ls runs/08-notification-dispatcher/
cat runs/08-notification-dispatcher/<最新时间戳>/summary.json
```
