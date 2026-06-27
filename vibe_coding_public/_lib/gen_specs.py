#!/usr/bin/env python3
"""
Generate services/<id>/SPEC.md for all 15 microservices.

The catalog (descriptions + endpoints + exerciser hints) is declared inline
below so this file is self-contained. Per-service language / deps / faults
are sourced from _lib/scaffold.py's SERVICES list.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

sys.path.insert(0, str(ROOT / "_lib"))
from scaffold import SERVICES  # type: ignore  # noqa: E402

# ---------------------------------------------------------------------------
# Per-service description in Chinese + endpoint list. Keys must match the
# SERVICES catalog ids.
# ---------------------------------------------------------------------------
DESC: dict[str, dict] = {
    "01-catalog-api": {
        "summary": "商品目录服务。Python + FastAPI + psycopg。维护 `products` 表（id/name/price_cents/stock_qty），启动时自动建表并插入 5 条种子数据。",
        "endpoints": [
            "GET  /healthz",
            "GET  /products            列出所有商品",
            "GET  /products/{id}       查询单个商品",
            "POST /products            创建商品 body: {\"name\":\"...\",\"price_cents\":N,\"stock_qty\":N}",
        ],
        "behavior": "所有读写都查询 Postgres。Postgres 故障时返回 502，并在 stdout 打印 `ERROR postgres ...` 行。",
    },
    "02-cart-service": {
        "summary": "购物车服务。Go + net/http + go-redis。每个用户购物车以 `cart:<uid>` Hash 存储。",
        "endpoints": [
            "GET    /healthz",
            "GET    /cart/{uid}             获取购物车",
            "POST   /cart/{uid}/items       追加商品 body: {\"sku\":\"...\",\"qty\":N}",
            "DELETE /cart/{uid}             清空购物车",
        ],
        "behavior": "Redis 故障时返回 502，handler 用 `ERROR ...` 打印连接错误。",
    },
    "03-order-api": {
        "summary": "订单 API。Java + Javalin + JDBC + Jedis。下单流程：写 Postgres `orders` 表，并向 `orders:queue` Stream XADD 事件。",
        "endpoints": [
            "GET  /healthz",
            "POST /orders              创建订单 body: {\"user_id\":\"...\",\"items\":[...]}",
            "GET  /orders/{id}         查询订单",
        ],
        "behavior": "Postgres 失败直接返回 502；Redis Stream XADD 失败仅 ERROR 记录但订单仍成功（fan-out best-effort）。",
    },
    "04-payment-gateway": {
        "summary": "支付网关。C# / ASP.NET Core 8 Minimal API。把扣款请求转发到 mock-upstream `/charge` 上游。",
        "endpoints": [
            "GET  /healthz",
            "POST /charge              扣款 body: {\"user_id\":\"...\",\"amount_cents\":N}",
        ],
        "behavior": "HttpClient 2s 超时；上游 5xx / 超时 / 拒连都会以 `ERROR upstream ...` 打印并返回 502/504。",
    },
    "05-inventory-tracker": {
        "summary": "库存追踪。Go + net/http + go-redis。后台生产者每 3s 向 `orders:queue` XADD 模拟订单，消费者用 XREADGROUP 消费并 DECRBY `inv:<sku>` 库存。",
        "endpoints": [
            "GET /healthz",
            "GET /stats               消费计数和错误数",
            "GET /stock/{sku}         查询某 SKU 当前库存",
        ],
        "behavior": "内置后台 loop 持续访问 redis-cache 和 redis-stream，任何故障都会以 `ERROR ...` 打印。",
    },
    "06-user-profile": {
        "summary": "用户档案。Java + Javalin + JDBC。`users` 表（id/email/name/created_at）。",
        "endpoints": [
            "GET  /healthz",
            "POST /users              创建用户",
            "GET  /users/{id}         查询用户",
            "PUT  /users/{id}         更新用户",
        ],
        "behavior": "纯 Postgres CRUD。DB 故障时返回 502 + `ERROR pg ...` 日志。",
    },
    "07-session-cache": {
        "summary": "会话缓存。Go + go-redis。Redis SETEX 存放 `sess:<token>`，TTL 3600s。",
        "endpoints": [
            "GET    /healthz",
            "POST   /session                  body: {\"user_id\":\"...\"} → {\"token\":\"...\"}",
            "GET    /session/{token}",
            "DELETE /session/{token}",
        ],
        "behavior": "Redis 操作 2s 超时；故障时返回 502 + `ERROR redis ...` 日志。",
    },
    "08-notification-dispatcher": {
        "summary": "通知调度。Python + FastAPI + redis.asyncio + httpx。后台生产者每 2s 向 `notifications:queue` XADD 通知；消费者用 XREADGROUP 拉取，POST 到 mock-upstream `/send`。",
        "endpoints": [
            "GET /healthz",
            "GET /stats               dispatched / failed 计数",
        ],
        "behavior": "队列或上游故障都会在 stdout 输出 `ERROR ...`，并把 failed 计数加一。",
    },
    "09-order-processor": {
        "summary": "订单处理器。Java + Javalin + JDBC + Jedis。后台生产者每 5s 向 `orders:queue` XADD 订单；消费者 XREADGROUP 拉取后 INSERT 到 `processed_orders` 表并 XACK。",
        "endpoints": [
            "GET /healthz",
            "GET /stats               consumed / errors 计数",
        ],
        "behavior": "Stream 或 Postgres 故障时 errors 计数增加并打印 `ERROR ...`。",
    },
    "10-search-indexer": {
        "summary": "搜索索引器。Python + FastAPI + psycopg + redis.asyncio。每 5s 从 Postgres 读取 products 写入 `idx:product:{id}` 到 redis-cache（EX=300）。",
        "endpoints": [
            "GET /healthz",
            "GET /stats               indexed_total / errors 计数",
            "GET /index/{pid}         查询某 product 的索引内容",
        ],
        "behavior": "两个依赖任一故障都会在 indexer loop 中产生 `ERROR ...` 日志。",
    },
    "11-image-resizer": {
        "summary": "图片处理。C++ + cpp-httplib（单头文件，CMake 在 configure 时下载）。POST 二进制流写入 `/tmp/resized/<id>`，再用 id 读回。不依赖任何外部组件，仅用来验证 F01/F02。",
        "endpoints": [
            "GET  /healthz",
            "POST /resize             body 为原始字节 → {\"id\":\"...\",\"bytes\":N}",
            "GET  /resized/{id}       下载原始字节",
        ],
        "behavior": "本地磁盘 IO 服务。F01 重启后 /tmp 会被清空；F02 注入网络延迟时 client 端能观测到响应慢。",
    },
    "12-rate-limiter-proxy": {
        "summary": "限流代理。Go + go-redis。对每个 client IP 做固定窗口计数（`rl:<ip>:<minute>`，限额 100/min），通过后反向代理到 mock-upstream。",
        "endpoints": [
            "GET /healthz",
            "GET /api/*               透传到 mock-upstream，先检查 redis 限流",
        ],
        "behavior": "Redis 故障时计数失败 → fail-open 但打印 `ERROR redis ...`；上游 5xx 也以 `ERROR upstream ...` 打印。",
    },
    "13-auth-token-svc": {
        "summary": "鉴权 / token 服务。Java + Javalin + JDBC，自研 HS256 JWT（HmacSHA256 + Base64URL）。`auth_users` 表存邮箱 + sha256 密码。",
        "endpoints": [
            "GET  /healthz",
            "POST /signup             body: {\"email\":\"...\",\"password\":\"...\"}",
            "POST /token              body 同上 → {\"token\":\"...\"}",
            "GET  /verify             header: Authorization: Bearer <token>",
        ],
        "behavior": "登录 / 注册都要查 Postgres。DB 故障返回 502 + `ERROR pg ...` 日志。/verify 不查 DB。",
    },
    "14-metrics-aggregator": {
        "summary": "指标聚合器。Python + FastAPI + redis.asyncio。后台生产者每 1s 向 `metrics:queue` XADD 4 种指标轮流；消费者 INCRBY 计数器 `counter:<metric>`。",
        "endpoints": [
            "GET /healthz",
            "GET /metrics              Prometheus 风格文本输出当前计数器",
        ],
        "behavior": "队列或 cache 故障在 consumer/producer loop 中打印 `ERROR ...` 并增加 errors 计数。",
    },
    "15-webhook-fanout": {
        "summary": "Webhook 扇出器。C# / ASP.NET Core 8。POST 进来的 body 并行扇出到 3 个 mock-upstream 路径（/dest-1/2/3）。",
        "endpoints": [
            "GET  /healthz",
            "POST /webhook             把 body 同时转发到三个上游，返回各自的 status",
        ],
        "behavior": "任一上游 5xx/超时都会在 stdout 输出 `ERROR upstream ...` 并把整体响应改为 502。",
    },
}


SPEC_TPL = """# {svc_id} — {summary_first_line}

> {summary_rest}

## 基本信息

| 字段 | 值 |
| --- | --- |
| 服务 ID | `{svc_id}` |
| Pod label | `app={app}` |
| 镜像 | `vibe/{svc_id}:dev`（`imagePullPolicy: Never`） |
| 语言 / 技术栈 | {lang_label} |
| 监听端口 | 8080 |
| 依赖 | {deps_label} |
| 适用故障 | {faults_label} |
| 健康检查 | `GET /healthz` |

## 端点

```
{endpoints_block}
```

## 行为约定

{behavior}

---

## 如何运行

每个服务下都有一个 `run.sh`，下面是常用子命令（在仓库根目录执行）：

```bash
# 1) 构建镜像并 kind load 进 'vibe' 集群
bash services/{svc_id}/run.sh build

# 2) 应用 k8s 清单
bash services/{svc_id}/run.sh deploy

# 3) 等待 rollout 就绪
bash services/{svc_id}/run.sh wait

# 4) 烟囱测试（默认 curl {smoke_path_default}）
bash services/{svc_id}/run.sh smoke
```

也可以用 Makefile 一行：

```bash
make build  SVC={svc_id}
make deploy SVC={svc_id}
make wait   SVC={svc_id}
make smoke  SVC={svc_id}
```

## 如何注射故障

本服务支持的故障：

{faults_table}

可用命令（每条独立注射，会在 `runs/{svc_id}/<时间戳>/<故障>/` 目录下生成 `meta.json` 等元数据）：

```bash
{inject_examples}
```

注射期间，框架会自动启动一个针对本服务的端口转发，并按 1Hz 反复调用 `services/{svc_id}/exercise.sh` 中的 `exercise_once()`，向服务发送真实流量，从而让被故障打中的代码路径在日志中暴露错误信号。

## 如何检测

判定逻辑是 **故障注射后的日志窗口分析**：判官读取本服务在故障注射时段（`t_start ~ t_end`）的 pod 日志，并按 `judge/oracle.yaml` 中的正则去匹配。匹配成功 → `caught=true`。

判定命令：

```bash
# 对最新一次注射结果做判定（顶层目录或单个 fault 目录都支持）
bash services/{svc_id}/run.sh judge

# 或者直接调判官
python3 judge/judge.py runs/{svc_id}/<时间戳>/
```

输出：每个 fault 子目录写入 `verdict.json`，顶层目录写入 `summary.json`，控制台打印 `caught N/M` 汇总。

## 一键演示

```bash
make demo SVC={svc_id}
# 等价于：build + deploy + wait + smoke + (inject 所有适用故障) + judge
```

完成后查看：

```bash
ls runs/{svc_id}/
cat runs/{svc_id}/<最新时间戳>/summary.json
```
"""

FAULT_DESCRIPTIONS = {
    "F01-pod-kill":       ("60s",  "杀掉本服务的 pod（PodChaos one-shot）"),
    "F02-network-delay":  ("120s", "对本服务注入 500ms ± 100ms 网络延迟（NetworkChaos）"),
    "F03-upstream-fail":  ("120s", "让 mock-upstream 返回 500 错误（HTTPChaos Response）"),
    "F04-upstream-slow":  ("120s", "让 mock-upstream 响应延迟（HTTPChaos Response）"),
    "F05-db-down":        ("60s",  "杀掉 postgres pod"),
    "F06-db-slow":        ("120s", "对 postgres pod 注入网络延迟"),
    "F07-cache-down":     ("60s",  "杀掉 redis-cache pod"),
    "F08-cache-slow":     ("120s", "对 redis-cache 注入网络延迟"),
    "F09-queue-down":     ("60s",  "杀掉 redis-stream pod"),
    "F10-queue-slow":     ("120s", "对 redis-stream 注入网络延迟"),
}

LANG_LABEL = {
    "python": "Python 3.12 / FastAPI",
    "go":     "Go 1.22 / net/http",
    "java":   "Java 21 / Javalin 6",
    "csharp": "C# / .NET 8 Minimal API",
    "cpp":    "C++17 / cpp-httplib",
}


def render(svc: dict) -> str:
    d = DESC[svc["id"]]
    summary_first_line = d["summary"].split("。", 1)[0] + "。" if "。" in d["summary"] else d["summary"]
    summary_rest = d["summary"][len(summary_first_line):].lstrip()
    if not summary_rest:
        summary_rest = "_(see endpoints below)_"

    deps_label = "无外部依赖" if not svc["deps"] else "、".join(svc["deps"])

    faults_label = ", ".join(f"`{f}`" for f in svc["faults"])
    faults_table_lines = ["| ID | 窗口 | 说明 |", "| --- | --- | --- |"]
    for f in svc["faults"]:
        win, desc = FAULT_DESCRIPTIONS[f]
        faults_table_lines.append(f"| `{f}` | {win} | {desc} |")
    faults_table = "\n".join(faults_table_lines)

    inject_examples = "\n".join(
        f"bash services/{svc['id']}/run.sh inject {f}"
        for f in svc["faults"]
    )

    smoke_path_default = svc.get("smoke_path", "/healthz")
    return SPEC_TPL.format(
        svc_id=svc["id"],
        app=svc["app"],
        lang_label=LANG_LABEL[svc["lang"]],
        deps_label=deps_label,
        faults_label=faults_label,
        endpoints_block="\n".join(d["endpoints"]),
        behavior=d["behavior"],
        smoke_path_default=smoke_path_default,
        faults_table=faults_table,
        inject_examples=inject_examples,
        summary_first_line=summary_first_line,
        summary_rest=summary_rest,
    )


def main() -> int:
    written = 0
    for svc in SERVICES:
        if svc["id"] not in DESC:
            print(f"  skip {svc['id']} (no description)", file=sys.stderr)
            continue
        out = ROOT / "services" / svc["id"] / "SPEC.md"
        out.write_text(render(svc))
        print(f"-> {out.relative_to(ROOT)}")
        written += 1
    print(f"\n{written} SPEC.md files written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
