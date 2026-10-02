# repro-verdict

**论文复现的「可审计验收」工具。**

复现一篇论文，结束时通常只有一句模糊的感觉：「数字差不多对上了」。
repro-verdict 把这种感觉拆成两件可核对的事：

1. **确定性档位**——复现的数字是否落在你**动手之前**就定好的容差内；
2. **评审团评分**——这次复现是否可信：忠实、有证据、别人能重跑。

档位是纯算术，所以可审计；评审团是模型判断，所以明确标为判断。两者永不混在一起。

---

## 为什么要分两层

大多数「我复现了吗」的脚本只回答一个问题，却假装那就是另一个问题的答案。
只报 `RMSE 284.40 vs 284.83` 的脚本，说不出这次运行可不可信；
而只回答「看起来挺接近」的模型，说不出任何你能拿去核对的东西。

所以 repro-verdict 把它们分开：

| 层 | 回答的问题 | 手段 |
| --- | --- | --- |
| 档位 | 数字对上了吗 | 声称值 vs 实得值 的算术比较 |
| 评审团 | 这次运行该不该信 | 三个评审角色，各自返回结构化 JSON |

## 档位

档位有序：`A > B > C > F`，**总体档位取所有指标里最差的那个**，
所以一个失败项永远不会被一堆成功项掩盖。

| 档位 | 含义 |
| --- | --- |
| `A` | 落在严格相对容差内 |
| `B` | 落在宽松相对容差内 |
| `C` | 论文没声称值，但跑出了数字：流程通了 |
| `F` | 没有观测值，或超出宽松容差 |

容差默认 `A <= 0.1%`、`B <= 5%`，写在计划文件里——
也就是说**验收线在跑之前就写死了**，不是看到结果再讨价还价。

档位只回答「数字对上没有」。它还配了一个**覆盖率**数字，见下文「要求树」。

## 安装

```bash
pip install repro-verdict            # 核心，零依赖
pip install "repro-verdict[yaml]"    # 支持 .yaml 计划
pip install "repro-verdict[llm]"     # 支持评审团
```

不安装、直接从源码跑：

```bash
set PYTHONPATH=src
python -m repro_verdict.cli --help
```

## 快速开始

```bash
repro-verdict init repro-plan.yaml
repro-verdict check --plan repro-plan.yaml --runs runs/ --out REPRO_REPORT.md
```

启用评审团（任何 OpenAI 兼容端点都行，包括本地网关）：

```bash
set REPRO_VERDICT_API_KEY=...
set OPENAI_BASE_URL=http://127.0.0.1:8080/v1

repro-verdict check --plan repro-plan.yaml --runs runs/ ^
  --llm --model 你的模型名 --out REPRO_REPORT.md
```

退出码：达标 `0`，未达标 `1`，计划或运行文件有错 `2`——可直接进 CI。

## 计划文件

计划就是合同：在任何运行发生之前，固定住声称值、容差和目标档位。

字段含义：

- `claims`：论文声称的每个数字，用 `key` + `group` 定位（例如 `rmse` 下的 `A1` 路段）
- `tolerances`：A 档和 B 档的相对容差
- `environment`：算力、环境、数据——会喂给评审团，让它知道你的约束
- `gaps`：你没搞清楚的论文缺口，**明确写出来**，而不是偷偷猜
- `notes`：给自己的备注，同样进评审上下文

完整示例见 `examples/plan.example.yaml`。

## 运行文件

任何带 `metrics` 列表的 JSON 都能读（裸列表也行），现有的实验日志不用改写：

```json
{
  "run_id": "20261001-kelm-grid",
  "metrics": [
    { "key": "rmse", "group": "A1", "observed": 284.40, "unit": "vehs/h" }
  ]
}
```

可以传多个文件，也可以传一个目录（会读取其中所有 `*.json`）。

## 排序一致性

数字可以各自都很接近，而**结论**却翻了。当多个 group 共用一个指标 key
（路段、数据集、模型规模）时，repro-verdict 还会报告声称值与实得值的
Spearman 秩相关：

```
| metric | groups              | n | Spearman rho | ordering consistent |
| rmse   | A1, A2, A4, A8      | 4 | 1            | yes                 |
```

「逐项都对得上」叠加「rho 为负」，正是「数字看着没问题」掩盖结论已崩的典型情形。

## 要求树（覆盖率）

一串数字表达不了复现里**不是数字**的那部分：*方法到底实现了没有？*
论文声称四个 RMSE，但背后的工作是「搜索实现了」「滤波器按描述跑起来了」「消融跑出来了」。

所以计划里可以声明一棵**要求树**。每个叶子带权重、有部分学分，并落在阶梯的一级上：

| kind | 问的是 | 怎么判 |
| --- | --- | --- |
| `development` | 代码存在吗 | 复现者 attest，评审团审计 |
| `execution` | 真跑了吗 | 复现者 attest，评审团审计 |
| `result` | 数字对得上吗 | **纯算术**，与普通 claim 完全一样 |

报告里会同时给出档位与覆盖率：

```
Overall grade: B (same magnitude / ordering) — A: 2, B: 7, C: 0, F: 0
Requirement coverage: 46.2% (2/5 leaves earned)
```

两者矛盾时，报告会**明说**，而不是偷偷二选一：

```
Gate warnings — the numeric grade and the tree disagree
- numeric grade is B, but requirement 'kalman' (development) is unsatisfied
```

档位**不会**被要求树改写。把「没实现」悄悄折进档位，会让档位失去可审计性；
把矛盾摆出来才是诚实的做法。

## 证据溯源门禁

「这个数是本次复现产出的」应该是规则，不是承诺。在计划里写 `frozen_at`，
给观测值写 `produced_at`，**早于冻结时刻的观测一律拒收**——
上个月遗留的 JSON 不可能冒充这次的运行结果。

## 会降档的结构化缺口

缺口以前只是散文。现在它可以声明影响哪些 claim、以及用了什么兜底，
从而让一个**已声明的、有交代的**缺口不再被当成静默失败：

```yaml
gaps:
  - id: no-kf-leg
    text: "本次没有 Kalman 那一路，所以是 GSA-KELM 而不是 GSA-KELM-KF。"
    affects: [rmse_gsa@A8]
    resolved_by: "A8 只作量级参考，不判硬失败"
```

只有当缺口**既点名了 claim、又给出了兜底**时，才会把 `F` 降为 `C`。
没有兜底的缺口不改变任何判定；完全没有观测值的仍然算缺失。

## 评审团

三个角色，各自返回结构化表单，再加权成 0–10 分：

| 评审 | 关注 |
| --- | --- |
| Fidelity（忠实度） | 实现是否忠实论文、超参是否覆盖、没写的地方有没有坦白 |
| Evidence（证据） | 数字、基线、消融、种子离散度是否真的支撑结论 |
| Reproducibility（可复现性） | 脚本、环境、种子、数据——陌生人明天能不能重跑 |

每个评审都要给出 `Verdict` 和 `Confidence`；某个评审失败不会中断整轮，
失败会记在该评审名下，报告其余部分照常渲染。

每条 finding 必须**指明位置**并给出严重度，让评审可执行而不是一种情绪：

```
| location                  | severity | issue                                        |
| Requirement tree / kalman | high     | 只实现了 GSA-KELM 那一路 ...                 |
| Reproducer notes / kelm.py| medium   | gamma/sigma 来自网格搜索而非论文 ...          |
```

评审节始终自报有效率——**半个失败的评审团绝不能看起来像意见一致的评审团**：

```
Panel validity: 3/3 reviewers returned a parseable score
```

如果一个有效结果都没有，`check --llm` 退出码为 `2`。

## 审计评审团本身

覆盖率是算术，可审计；评审团是判断，**不度量它就只是感觉**。
`selfcheck` 在完全相同的输入上重复跑评审团，报告分数离散度与判定一致率：

```bash
repro-verdict selfcheck --plan repro-plan.yaml --runs runs/ --repeat 5 --temperature 0.7
```

这是**稳定性**检查，不是**有效性**检查：一个评审团可以稳定地错。
有效性需要人工标注的期望值，重复运行替代不了。

## Python API

```python
from repro_verdict import Claim, Observation, Tolerances, compare_claims

verdict = compare_claims(
    [Claim(key="rmse", group="A1", claimed=284.83)],
    [Observation(key="rmse", group="A1", observed=284.40)],
    Tolerances(a=0.001, b=0.05),
)

print(verdict.grade)              # Grade.B
print(verdict.comparisons[0].rel_err)
```

## 设计取舍

- **计划先行**：容差在跑之前就写死，档位才有意义，而不是事后凑
- **默认确定性**：评审团是可选开关（`--llm`），档位不依赖模型是否可达
- **没有隐藏状态**：缺观测就报缺失，绝不跳过；计划里没声称的观测也会被列出来
- **依赖无聊**：核心零依赖

## 致谢

评审团的思路——多个角色各返回结构化 JSON 评审再打分——来自
[Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)（Schmidgall 等）
与 The AI Scientist。本项目把这套回环从「论文录用」转向「复现验收」，
并补上了它们没有的确定性档位。

## 许可

MIT，见 [LICENSE](LICENSE)。
