# 06-user-profile — 用户档案。

> Java + Javalin + JDBC。`users` 表（id/email/name/created_at）。

## 基本信息

| 字段 | 值 |
| --- | --- |
| 服务 ID | `06-user-profile` |
| Pod label | `app=user-profile` |
| 镜像 | `vibe/06-user-profile:dev`（`imagePullPolicy: Never`） |
| 语言 / 技术栈 | Java 21 / Javalin 6 |
| 监听端口 | 8080 |
| 依赖 | postgres |
| 适用故障 | `F01-pod-kill`, `F02-network-delay`, `F05-db-down`, `F06-db-slow` |
| 健康检查 | `GET /healthz` |

## 端点

```
GET  /healthz
POST /users              创建用户
GET  /users/{id}         查询用户
PUT  /users/{id}         更新用户
```

## 行为约定

纯 Postgres CRUD。DB 故障时返回 502 + `ERROR pg ...` 日志。

---

## 如何运行

每个服务下都有一个 `run.sh`，下面是常用子命令（在仓库根目录执行）：

```bash
# 1) 构建镜像并 kind load 进 'vibe' 集群
bash services/06-user-profile/run.sh build

# 2) 应用 k8s 清单
bash services/06-user-profile/run.sh deploy

# 3) 等待 rollout 就绪
bash services/06-user-profile/run.sh wait

# 4) 烟囱测试（默认 curl /healthz）
bash services/06-user-profile/run.sh smoke
```

也可以用 Makefile 一行：

```bash
make build  SVC=06-user-profile
make deploy SVC=06-user-profile
make wait   SVC=06-user-profile
make smoke  SVC=06-user-profile
```

## 如何注射故障

本服务支持的故障：

| ID | 窗口 | 说明 |
| --- | --- | --- |
| `F01-pod-kill` | 60s | 杀掉本服务的 pod（PodChaos one-shot） |
| `F02-network-delay` | 120s | 对本服务注入 500ms ± 100ms 网络延迟（NetworkChaos） |
| `F05-db-down` | 60s | 杀掉 postgres pod |
| `F06-db-slow` | 120s | 对 postgres pod 注入网络延迟 |

可用命令（每条独立注射，会在 `runs/06-user-profile/<时间戳>/<故障>/` 目录下生成 `meta.json` 等元数据）：

```bash
bash services/06-user-profile/run.sh inject F01-pod-kill
bash services/06-user-profile/run.sh inject F02-network-delay
bash services/06-user-profile/run.sh inject F05-db-down
bash services/06-user-profile/run.sh inject F06-db-slow
```

注射期间，框架会自动启动一个针对本服务的端口转发，并按 1Hz 反复调用 `services/06-user-profile/exercise.sh` 中的 `exercise_once()`，向服务发送真实流量，从而让被故障打中的代码路径在日志中暴露错误信号。

## 如何检测

判定逻辑是 **故障注射后的日志窗口分析**：判官读取本服务在故障注射时段（`t_start ~ t_end`）的 pod 日志，并按 `judge/oracle.yaml` 中的正则去匹配。匹配成功 → `caught=true`。

判定命令：

```bash
# 对最新一次注射结果做判定（顶层目录或单个 fault 目录都支持）
bash services/06-user-profile/run.sh judge

# 或者直接调判官
python3 judge/judge.py runs/06-user-profile/<时间戳>/
```

输出：每个 fault 子目录写入 `verdict.json`，顶层目录写入 `summary.json`，控制台打印 `caught N/M` 汇总。

## 一键演示

```bash
make demo SVC=06-user-profile
# 等价于：build + deploy + wait + smoke + (inject 所有适用故障) + judge
```

完成后查看：

```bash
ls runs/06-user-profile/
cat runs/06-user-profile/<最新时间戳>/summary.json
```
