# 02-cart-service — 购物车服务。

> Go + net/http + go-redis。每个用户购物车以 `cart:<uid>` Hash 存储。

## 基本信息

| 字段 | 值 |
| --- | --- |
| 服务 ID | `02-cart-service` |
| Pod label | `app=cart-service` |
| 镜像 | `vibe/02-cart-service:dev`（`imagePullPolicy: Never`） |
| 语言 / 技术栈 | Go 1.22 / net/http |
| 监听端口 | 8080 |
| 依赖 | redis_cache |
| 适用故障 | `F01-pod-kill`, `F02-network-delay`, `F07-cache-down`, `F08-cache-slow` |
| 健康检查 | `GET /healthz` |

## 端点

```
GET    /healthz
GET    /cart/{uid}             获取购物车
POST   /cart/{uid}/items       追加商品 body: {"sku":"...","qty":N}
DELETE /cart/{uid}             清空购物车
```

## 行为约定

Redis 故障时返回 502，handler 用 `ERROR ...` 打印连接错误。

---

## 如何运行

每个服务下都有一个 `run.sh`，下面是常用子命令（在仓库根目录执行）：

```bash
# 1) 构建镜像并 kind load 进 'vibe' 集群
bash services/02-cart-service/run.sh build

# 2) 应用 k8s 清单
bash services/02-cart-service/run.sh deploy

# 3) 等待 rollout 就绪
bash services/02-cart-service/run.sh wait

# 4) 烟囱测试（默认 curl /cart/u1）
bash services/02-cart-service/run.sh smoke
```

也可以用 Makefile 一行：

```bash
make build  SVC=02-cart-service
make deploy SVC=02-cart-service
make wait   SVC=02-cart-service
make smoke  SVC=02-cart-service
```

## 如何注射故障

本服务支持的故障：

| ID | 窗口 | 说明 |
| --- | --- | --- |
| `F01-pod-kill` | 60s | 杀掉本服务的 pod（PodChaos one-shot） |
| `F02-network-delay` | 120s | 对本服务注入 500ms ± 100ms 网络延迟（NetworkChaos） |
| `F07-cache-down` | 60s | 杀掉 redis-cache pod |
| `F08-cache-slow` | 120s | 对 redis-cache 注入网络延迟 |

可用命令（每条独立注射，会在 `runs/02-cart-service/<时间戳>/<故障>/` 目录下生成 `meta.json` 等元数据）：

```bash
bash services/02-cart-service/run.sh inject F01-pod-kill
bash services/02-cart-service/run.sh inject F02-network-delay
bash services/02-cart-service/run.sh inject F07-cache-down
bash services/02-cart-service/run.sh inject F08-cache-slow
```

注射期间，框架会自动启动一个针对本服务的端口转发，并按 1Hz 反复调用 `services/02-cart-service/exercise.sh` 中的 `exercise_once()`，向服务发送真实流量，从而让被故障打中的代码路径在日志中暴露错误信号。

## 如何检测

判定逻辑是 **故障注射后的日志窗口分析**：判官读取本服务在故障注射时段（`t_start ~ t_end`）的 pod 日志，并按 `judge/oracle.yaml` 中的正则去匹配。匹配成功 → `caught=true`。

判定命令：

```bash
# 对最新一次注射结果做判定（顶层目录或单个 fault 目录都支持）
bash services/02-cart-service/run.sh judge

# 或者直接调判官
python3 judge/judge.py runs/02-cart-service/<时间戳>/
```

输出：每个 fault 子目录写入 `verdict.json`，顶层目录写入 `summary.json`，控制台打印 `caught N/M` 汇总。

## 一键演示

```bash
make demo SVC=02-cart-service
# 等价于：build + deploy + wait + smoke + (inject 所有适用故障) + judge
```

完成后查看：

```bash
ls runs/02-cart-service/
cat runs/02-cart-service/<最新时间戳>/summary.json
```
