# obs-real-bench 的 Instances 来源与 F1 指标说明

这份文档解释两个问题：第一，`obs-real-bench` 如何从原始 repository 中获得 benchmark instances；第二，`Key F1` / `KeyBag F1` 和 `Position F1` 是怎么计算出来的。文本按论文写作素材组织，后续可以直接交给 agent 改写成论文段落。

## 1. Instance 是什么

`obs-real-bench` 的基本任务单元是 function-level instance。一个 instance 对应原始代码仓库中的一个真实函数。它不是合成代码，也不是把答案直接存在 JSON 里，而是用 JSON 记录“到哪里去找这个真实函数”。

每个 instance 至少包含三类关键信息：

1. `repo.local_path`：原始 repository 的本地 checkout 路径。
2. `target.file`：目标函数所在的源文件。
3. `target.function`：要评测的函数或方法名。

运行 benchmark 时，pipeline 会读取 `repo.local_path + target.file` 得到原始源码；原始源码里的目标函数就是 ground truth。随后 benchmark 会把该函数中的 observability 代码去掉，让模型补回来，再把模型输出和原始函数中的 observability 行为进行比较。

简言之：instance JSON 是指向真实 repo 中真实函数的索引；原始 repo 是 ground truth 的来源。

## 2. Instances 如何从原始 repo 挖出来

当前 expanded benchmark 主要由自动挖掘脚本生成，而不是靠早期的 `tools/build_instances.py` 骨架。核心脚本如下：

| 脚本 | 作用 |
|---|---|
| `tools/mine.py` | 用 Python AST 挖 Python 函数。 |
| `tools/mine_polyglot.py` | 用 tree-sitter 挖 Go、Java、TypeScript、JavaScript、C#、C++、Ruby、Rust、PHP 等语言。 |
| `tools/filter_and_sample.py` | 对 raw mined instances 做过滤、去测试文件、采样和平衡。 |
| `tools/build_siblings.py` | 为 few-shot prompt 补充同文件里的 observability-bearing sibling functions。 |

### 2.1 候选函数发现

对于每个原始 repo，miner 会遍历源文件，解析函数或方法声明。一个函数会被保留下来，通常需要满足以下条件：

1. 源文件可以成功解析。
2. 函数不是过短的 trivial function，例如 Python 要满足最小 statement 数，polyglot mining 要满足最小行数。
3. 函数内部包含 observability 相关代码，例如 logging、tracing、metrics、span attribute、span event、counter、histogram，或者函数名中带有 observability 语义的 helper call。
4. 测试文件、生成文件、依赖目录和构建产物会被过滤掉。

Python 路径由 `tools/mine.py` 实现。它用 Python `ast` 枚举 top-level function 和 class method，并检查函数体中是否有 observability call 或 observability assignment。

非 Python 路径由 `tools/mine_polyglot.py` 实现。它使用 tree-sitter parser 找函数节点，并用语言相关的 observability token 判断函数是否包含 instrumentation。例如 TypeScript 中会匹配 `tracer.startSpan`、`tracer.startActiveSpan`、`.setAttribute(`、`.addEvent(`、`counter.add(`、`histogram.record(`、`logger.` 等 token。

### 2.2 Instance JSON 生成

每个通过筛选的候选函数会被写成一个 JSON 文件，放在 `instances/function/` 下。JSON 记录 repo、源文件、目标函数、语言和源码位置等信息。

一个真实例子如下：

```json
{
  "instance_id": "strapi__ts__misc__index__run__L77-v1",
  "schema_version": "0.1",
  "tier": "function",
  "_auto_mined": true,
  "_runnable": true,
  "repo": {
    "name": "strapi/strapi",
    "local_path": "../source_repos/strapi__strapi",
    "_base_commit": "source checkout required; record the commit used for reproduction"
  },
  "target": {
    "language": "typescript",
    "file": "packages/cli/create-strapi-app/src/index.ts",
    "function": "run"
  },
  "task": {
    "available_imports": []
  },
  "_meta": {
    "service": "misc",
    "class": null,
    "symbol": "run",
    "start_line": 77,
    "n_lines": 152,
    "n_obs_tokens": 1,
    "span_byte_range": [3102, 7732]
  },
  "siblings": []
}
```

这个例子表示：benchmark 会打开本地准备好的原始 repo checkout，读取 `packages/cli/create-strapi-app/src/index.ts`，找到 TypeScript 函数 `run`。这个原始函数就是该 instance 的 ground truth。`_meta.start_line` 和 `_meta.span_byte_range` 只是帮助定位函数，不是模型答案。

### 2.3 过滤与采样

raw mining 后，`tools/filter_and_sample.py` 会做 hygiene filtering 和 balanced sampling：

1. 按路径和文件名过滤 test/spec 文件。
2. 限制单个源文件最多贡献的 instances 数量，避免一个 telemetry-heavy 文件支配数据集。
3. 限制单个 repo 最多贡献的 instances 数量，降低 repository imbalance。
4. 使用固定 random seed 做稳定采样。

因此，最终的 `instances/function/` 不是简单地收下所有 raw candidates，而是经过了质量过滤和分布平衡。

### 2.4 Few-shot sibling examples

`p_fewshot` prompt 会使用 sibling functions。siblings 不是现场搜索的，而是提前由 `tools/build_siblings.py` 写进每个 instance JSON。

生成 siblings 的规则是：

1. 读取与目标函数相同的 ground-truth 源文件。
2. 枚举同文件中的其他函数或方法。
3. 排除目标函数本身。
4. 对每个 sibling 提取 ground-truth observability sites。
5. 只保留 `n_gt > 0` 的 sibling。
6. 按 `n_gt` 从大到小排序，数量相同则按函数名排序。
7. 最多写入前 `K` 个 sibling 到 instance JSON。

运行 `p_fewshot` 时，prompt 会把这些 sibling 的原始函数体插入进去，并且 sibling 中的 observability 保持完整。它们相当于“同一个文件里其他函数是怎么写 observability 的”这种局部代码风格参考。

## 3. 一个 instance 运行时发生什么

`tools/pilot.py` 是核心运行脚本。对每个 instance，它执行如下流程：

1. 加载 `instances/function/<instance_id>.json`。
2. 根据 `repo.local_path` 定位原始 repo。
3. 读取 `target.file` 指向的原始源码，作为 ground truth。
4. 从目标函数中 strip 掉 observability 代码。
5. 渲染 prompt，包括 stripped target function、module context、imports，以及可选 siblings。
6. 调用 API backend 或 Copilot agent backend。
7. 从模型响应中提取生成的目标函数。
8. 把生成函数 splice 回 stripped source。
9. 从 ground truth 和模型输出中分别提取 observability sites。
10. 计算 legacy score、Position F1、Key F1、KeyBag F1，并写入 result/summary。

这里的评分不是 whole-file text similarity。benchmark 真正关心的是：模型是否在正确的业务逻辑位置恢复了 observability，以及恢复的观测内容是否和原始代码表达了相同概念。

## 4. Position F1 是怎么来的

`Position F1` 在结果里叫 `pos_f1`。它衡量模型是否把 observability 放在了正确的位置。

计算思想如下：

1. 把函数里的非 observability 语句视为 business anchors。
2. observability 语句不作为 anchor，而是落在 anchors 之间的 slot/bucket 中。
3. 对 ground truth 和模型输出分别得到一串 business anchors 和 bucket observability 标记。
4. 用 `difflib.SequenceMatcher` 对齐 ground truth 和模型输出的 anchors。
5. 在对齐后的 bucket 上比较是否存在 observability。

每个 bucket 是一个二分类判断：该位置有没有 observability。

```text
TP = GT 有 observability，模型也有
FP = GT 没有 observability，模型却加了
FN = GT 有 observability，模型漏掉了

precision = TP / (TP + FP)
recall    = TP / (TP + FN)
pos_f1    = 2 * precision * recall / (precision + recall)
```

例子：

```text
GT buckets:    [obs, none, obs]
Model buckets: [obs, obs,  none]

TP = 1   第一个位置放对了
FP = 1   第二个位置模型多加了 observability
FN = 1   第三个位置模型漏掉了 observability

precision = 1 / (1 + 1) = 0.5
recall    = 1 / (1 + 1) = 0.5
pos_f1    = 0.5
```

所以 `pos_f1` 回答的是位置问题：模型有没有在原始代码应该观测的逻辑位置加 observability。它不关心 attribute name、log message 或 span name 是否完全正确。

## 5. Key F1 和 KeyBag F1 是怎么来的

repo 里有两个相关指标，写论文时要区分：

| 指标 | 字段名 | 含义 |
|---|---|---|
| Strict Key F1 | `key_f1` | 比较严格的 key set，例如 span name、attribute key、event name。 |
| KeyBag F1 | `key_bag_f1` | 比较宽松的 semantic token bag，是当前 README 推荐的 v2.x 主指标。 |

用户口头说的 “key f1” 在当前论文主结果中通常应写成 `KeyBag F1`，因为 README 明确说 primary metric 是 **Key Bag F1 under STRICT filtering**。

### 5.1 Strict Key F1

Strict Key F1 只抽取 observability API 中显式出现的 key，比如：

1. `tracer.start_as_current_span("name")` 中的 span name。
2. `span.set_attribute("k", v)` 中的 attribute key。
3. `span.set_attributes({"k1": v1, "k2": v2})` 中的 dict keys。
4. `span.add_event("evt")` 中的 event name。

它只在位置对齐、且 GT bucket 中确实有 key 的情况下比较。若 GT 是纯 log，没有可比较 key，则这个 bucket 不进入 strict key comparison。

### 5.2 KeyBag F1

KeyBag F1 更适合作为论文主指标，因为它不要求字符串完全一致，而是比较 observability 语句表达的语义概念。

对每个可比较 bucket，scorer 会从 observability 语句中抽取 token bag。来源包括：

1. string literal。
2. identifier name。
3. attribute 或 method name。
4. keyword argument name。

随后按 `.`, `_`, `-`, `/`, 空白和 camelCase 边界切词，并去掉纯数字、过短 token、以及 observability framework stop words，例如 `logger`、`span`、`tracer`、`metric`、`set_attribute`、`record_exception` 等。

这样做的目的，是评价模型是否恢复了“观测什么”，而不是是否逐字符复现了原始 API 调用。

例子：

```text
GT statement:
span.set_attribute("app.product.id", request_product_id)

GT keyword bag:
{app, product, request}

Model statement:
span.set_attribute("product.id", str(request_product_id))

Model keyword bag:
{product, request, str}
```

两边重叠 token 是 `{product, request}`，因此：

```text
TP = 2   product, request
FP = 1   str
FN = 1   app

precision  = 2 / (2 + 1) = 0.667
recall     = 2 / (2 + 1) = 0.667
key_bag_f1 = 0.667
```

KeyBag F1 会在整个函数的所有 comparable buckets 上累计 token-level TP、FP、FN，再计算 precision、recall 和 F1。如果没有任何 comparable bucket，则该 cell 的 `key_bag_f1` 是 `null`。

## 6. 一个端到端例子：从去除 observability 到打分

下面用一个小的 toy example 说明完整流程。真实 benchmark 会从原始 repo 读取函数；这里为了便于说明，直接写出 ground truth、strip 后给模型的版本，以及模型生成版本。

### 6.1 原始 ground truth 函数

原始 repo 中的真实函数可能长这样：

```python
def checkout(order):
  user = load_user(order.user_id)
  span.set_attribute("checkout.user_id", order.user_id)

  payment = charge_card(order.card, order.total)
  span.add_event("payment_charged")

  receipt = save_receipt(order.id, payment.id)
  logger.info("checkout complete", extra={"order_id": order.id})
  return receipt
```

这里有三处 observability：

1. `span.set_attribute("checkout.user_id", ...)`：记录用户相关 attribute。
2. `span.add_event("payment_charged")`：记录支付完成事件。
3. `logger.info("checkout complete", extra={"order_id": ...})`：记录 checkout 完成日志。

### 6.2 Strip 后给模型的函数

benchmark 会把目标函数中的 observability statements 去掉，业务逻辑保留：

```python
def checkout(order):
  user = load_user(order.user_id)

  payment = charge_card(order.card, order.total)

  receipt = save_receipt(order.id, payment.id)
  return receipt
```

模型看到的是这个 stripped function。它需要根据 prompt、上下文、imports、siblings 等信息把 observability 补回来。

### 6.3 模型生成的函数

假设模型生成如下版本：

```python
def checkout(order):
  logger.info("start checkout")

  user = load_user(order.user_id)
  span.set_attribute("user.id", order.user_id)

  payment = charge_card(order.card, order.total)

  receipt = save_receipt(order.id, payment.id)
  logger.info("checkout finished", extra={"receipt_id": receipt.id})
  return receipt
```

这个输出有四种典型现象：

1. 模型在函数开头多加了 `logger.info("start checkout")`，这是 GT 没有的位置。
2. 模型在 `load_user` 后加了 span attribute，位置对了，但 key 从 `checkout.user_id` 变成了 `user.id`。
3. 模型漏掉了 `payment_charged` event。
4. 模型在 `save_receipt` 后加了日志，位置对了，但内容从 `checkout complete / order_id` 变成了 `checkout finished / receipt_id`。

### 6.4 Position F1 怎么打

先把非 observability 业务语句当作 anchors：

```text
B1 = user = load_user(order.user_id)
B2 = payment = charge_card(order.card, order.total)
B3 = receipt = save_receipt(order.id, payment.id)
B4 = return receipt
```

然后比较 anchors 之间的 bucket 是否有 observability：

```text
Bucket 0: before B1
Bucket 1: between B1 and B2
Bucket 2: between B2 and B3
Bucket 3: between B3 and B4
Bucket 4: after B4
```

GT 和模型的 bucket 标记是：

```text
GT:    [none, obs,  obs,  obs,  none]
Model: [obs,  obs,  none, obs,  none]
```

因此：

```text
TP = 2   Bucket 1 和 Bucket 3 都有 obs，位置对了
FP = 1   Bucket 0 模型多加了 obs
FN = 1   Bucket 2 GT 有 obs，但模型漏掉了

pos_precision = 2 / (2 + 1) = 0.667
pos_recall    = 2 / (2 + 1) = 0.667
pos_f1        = 0.667
```

这说明模型有一部分位置是对的，但它额外加了一个开头日志，并漏掉了 payment 后面的 event。

### 6.5 Strict Key F1 怎么打

Strict Key F1 只看显式 key，例如 span attribute key、span event name。它不会把普通 log message 当成严格 key 来比较。

在这个例子里，真正可比较的 strict key bucket 是 Bucket 1：

```text
GT strict keys:    {checkout.user_id}
Model strict keys: {user.id}
```

两者没有完全相同的 key：

```text
key_tp = 0
key_fp = 1   user.id
key_fn = 1   checkout.user_id

key_precision = 0 / (0 + 1) = 0
key_recall    = 0 / (0 + 1) = 0
key_f1        = 0
```

Strict Key F1 很严格：`checkout.user_id` 和 `user.id` 虽然语义接近，但字符串 key 不一样，所以不给分。

### 6.6 KeyBag F1 怎么打

KeyBag F1 更宽松，它把 observability 语句里的字符串、变量名、attribute/member 名等切成 semantic tokens，再比较 token bag。

只看 GT 和模型都放了 obs 的 comparable buckets，即 Bucket 1 和 Bucket 3。

Bucket 1：

```text
GT statement:    span.set_attribute("checkout.user_id", order.user_id)
Model statement: span.set_attribute("user.id", order.user_id)

GT token bag:    {checkout, user, order}
Model token bag: {user, order}

TP = 2   user, order
FP = 0
FN = 1   checkout
```

Bucket 3：

```text
GT statement:    logger.info("checkout complete", extra={"order_id": order.id})
Model statement: logger.info("checkout finished", extra={"receipt_id": receipt.id})

GT token bag:    {checkout, complete, order}
Model token bag: {checkout, finished, receipt}

TP = 1   checkout
FP = 2   finished, receipt
FN = 2   complete, order
```

把两个 comparable buckets 加起来：

```text
key_bag_tp = 3
key_bag_fp = 2
key_bag_fn = 3

key_bag_precision = 3 / (3 + 2) = 0.600
key_bag_recall    = 3 / (3 + 3) = 0.500
key_bag_f1        = 2 * 0.600 * 0.500 / (0.600 + 0.500) = 0.545
```

这个例子展示了两种内容评分的差异：Strict Key F1 因为 key 字符串不完全一致而给 `0`；KeyBag F1 则能给部分语义 credit，因为模型至少恢复了 `user`、`order`、`checkout` 这些概念。

### 6.7 这个例子对应的结果形状

如果把上面的 toy example 写成一个 `summary.json` cell，大致会长这样：

```json
{
  "instance": "toy__py__checkout__checkout__L1",
  "prompt": "p_fewshot",
  "model": "example-model",
  "n_gt": 3,
  "n_llm": 3,
  "pos_precision": 0.667,
  "pos_recall": 0.667,
  "pos_f1": 0.667,
  "key_precision": 0.0,
  "key_recall": 0.0,
  "key_f1": 0.0,
  "key_bag_precision": 0.600,
  "key_bag_recall": 0.500,
  "key_bag_f1": 0.545
}
```

注意：这个例子是为解释机制而构造的 simplified example。真实 scorer 会用 AST 或 tree-sitter 提取 observability statements、对齐 anchors，并从 `anchor_score.buckets` 中汇总这些字段。

## 7. STRICT aggregation 是什么

论文级汇总使用 STRICT policy。`tools/aggregate_repo_lang.py` 中的规则是：

1. 如果 cell 的 `n_gt == 0`，说明 ground truth 函数没有 observability sites，没有恢复目标，因此从聚合中排除。
2. 对剩余 cells，如果 `key_bag_f1 == null` 或 `pos_f1 == null`，不是把 cell 删除，而是当作 `0` 计入平均。

这能避免模型在困难样本上产生 `null` 后被自动跳过。当前 README 也明确推荐使用 STRICT filtering 下的 KeyBag F1 作为主指标。

一个 summary row 的形状大致如下：

```json
{
  "instance": "...",
  "prompt": "p_fewshot",
  "model": "gpt-5.5",
  "n_gt": 3,
  "n_llm": 3,
  "pos_precision": 1.0,
  "pos_recall": 1.0,
  "pos_f1": 1.0,
  "key_bag_precision": 1.0,
  "key_bag_recall": 1.0,
  "key_bag_f1": 1.0
}
```

这表示模型在所有正确 bucket 上都恢复了 observability，并且在 comparable buckets 中恢复了全部语义 token。

## 8. 可直接放进论文的写法

下面这段可以作为论文草稿素材：

> We construct benchmark instances at function granularity from real-world repositories. For each repository, we parse source files, enumerate functions or methods, and retain non-trivial functions that contain observability-related code, including logging, tracing, metrics, span attributes, span events, or telemetry helper calls. Each retained function is materialized as an instance JSON that records the repository checkout, source file, target function, language, and source-location metadata. During evaluation, the harness reads the original source file from the recorded repository path, removes observability code from the target function, prompts a model or agent to restore it, and scores the generated function against the original implementation.

> We evaluate restoration quality along two axes. Position F1 measures whether restored observability appears in the same logical slots relative to business-statement anchors. The scorer aligns business anchors between the ground truth and generated function, then computes precision, recall, and F1 over buckets that contain observability code. KeyBag F1 measures whether the restored observability captures the same semantic concepts. For aligned buckets where both sides contain observability, the scorer extracts token bags from string literals, identifiers, member names, and keyword arguments, removes observability-framework stop words, and computes token-level precision, recall, and F1 against the ground truth. We report KeyBag F1 under STRICT filtering as the primary metric: cells with no ground-truth observability are excluded, while null metric values in remaining cells are counted as zero.

## 9. 一句话总结

Instances 是从真实 repo 中自动挖出的 observability-bearing 函数；`pos_f1` 衡量 observability 是否放在正确逻辑位置，`key_bag_f1` 衡量模型是否恢复了原始 observability 关注的语义概念。
