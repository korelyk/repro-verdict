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

## 评审团

三个角色，各自返回结构化表单，再加权成 0–10 分：

| 评审 | 关注 |
| --- | --- |
| Fidelity（忠实度） | 实现是否忠实论文、超参是否覆盖、没写的地方有没有坦白 |
| Evidence（证据） | 数字、基线、消融、种子离散度是否真的支撑结论 |
| Reproducibility（可复现性） | 脚本、环境、种子、数据——陌生人明天能不能重跑 |

每个评审都要给出 `Verdict` 和 `Confidence`；某个评审失败不会中断整轮，
失败会记在该评审名下，报告其余部分照常渲染。

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
