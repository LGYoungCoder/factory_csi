# Devpost submission – ready to paste / 提交表单内容

- **Project name:** Factory CSI – AI Manufacturing Quality Investigation Copilot
- **Category:** Frankenstein
- **Repository:** https://github.com/LGYoungCoder/factory_csi
- **Video:** `<youtube-url>`
- **App URL:** `<app-url>` (local demo: `make docker-up` → http://localhost:18473)
- **Built with:** kiro, python, fastapi, langgraph, litellm, deepseek, model-context-protocol, scipy, pandas, sqlite, sqlalchemy, react, typescript, vite, tailwindcss, echarts, docker

Use the English text for the form. The Chinese version is for reference and local presentations.

---

## Elevator pitch (≤ 200 characters)

**EN (193 characters):**

> An AI copilot for factory quality incidents: it gathers evidence across MES, equipment and test systems via MCP, proposes the next best check, and revises its verdict once an engineer approves.

**中文（73 字）：**

> AI 制造质量调查助手：通过 MCP 跨 MES、设备与测试系统取证，主动提出下一步最佳验证，经工程师批准后执行并修正判断，输出可追溯的调查报告。

---

## Project Story – English (paste into "About the project")

## Inspiration

In an automotive-component plant, the end-of-line (EOL) test is the last gate before a part ships. When one tester's failure rate suddenly jumps from about 2 % to about 18 %, a quality engineer has to answer a hard question quickly: are the parts really bad, is the tester measuring wrong, or did the product mix on that tester simply change?

The data needed to answer it is spread across separate systems: MES for orders, serial numbers and recipes, equipment monitoring for tightening torque, angle and program versions, and EOL test for measurements and reference samples. Engineers export spreadsheets and correlate them by hand. The costly mistake is not a missing chart. It is a confident early verdict that scraps good parts or ships bad ones.

Most "AI for manufacturing" demos stop at explaining what might have happened. We wanted an assistant that also says **what to check next**, waits for the engineer's approval, and **changes its mind when the evidence says so**.

## What it does

Factory CSI investigates an EOL quality anomaly on a fictional production line (Factory Alpha, Line A: ST-10 → ST-20 → ST-30 → EOL-A / EOL-B):

1. **Detects the anomaly statistically.** For each tester it compares the last 3 hours with the first 2 hours of the shift:
   $$\text{flag}(t) \iff p_{\text{Fisher}}(t) < 0.01 \;\wedge\; r_{\text{window}}(t) \ge 2\cdot\max\big(r_{\text{baseline}}(t),\,0.5\%\big)$$
2. **Collects cross-system evidence through MCP.** Our Industrial MCP Server exposes the simulated MES / equipment / EOL systems as 8 tools. The agent's tool calls are visible live in the UI.
3. **Grounds every claim in evidence.** Deterministic Python computes the statistics: Fisher, Kolmogorov–Smirnov, Mann–Whitney, OLS trends, stratification by product model and mix shift. Each finding becomes an Evidence item (`EV-007`) that links to raw records. The LLM may only cite existing Evidence IDs.
4. **Proposes the Next Best Verification.** It ranks up to three simulated checks (cross retest on the other tester, reference sample check, process configuration audit) and states how each possible outcome would support or contradict each hypothesis.
5. **Human in the loop.** The engineer approves, rejects all with a reason, or concludes. Approved checks run in the simulator, return new evidence, and the agent records an explicit judgment change such as *Tester drift: Medium → High, because EV-019*.
6. **Writes a traceable 10-section report** with timeline, evidence, verifications, judgment changes and the suspected affected product scope. It always uses "suspected" or "evidence-supported" wording, never "confirmed root cause".

## How we built it

- **Kiro, spec-driven.** We wrote 7 specs (simulator, MCP server, investigation engine, verification loop, API, UI, delivery) with 144 EARS requirements, then a cross-spec consistency pass. That pass found real conflicts before any code existed. For example, Scenario C's signal was too weak for our own detector to fire, and an LLM budget of 25 calls allowed only one verification round in the worst case. Steering files hold the rules: no fallback text, ground-truth isolation, citation rules. Three hooks run related tests and ruff on every Python save, tsc and eslint on every frontend save, and a secret guard on every save. The same MCP server is registered for Kiro's own agent.
- **Simulator with a hidden truth.** A seed-reproducible generator writes three artifacts per scenario:
  - `factory.db`, the observable systems;
  - `world_state.json`, the hidden physics, read only by the verification engine;
  - `ground_truth.json`, the answer key for tests and evaluation only.

  Import-linter contracts make it impossible for the backend or MCP server to import the answer key. Measurements follow a normalized model:
  $$z = \frac{v - m}{h},\qquad z_{\text{meas}} = z_{\text{true}} + b_{\text{tester}}(t) + \varepsilon,\quad \varepsilon \sim \mathcal{N}(0,\,0.1^2)$$
  Here $m$ is the midpoint and $h$ the half-width of the limits ($|z|\le 1$ passes). Tester drift is $b(t)=\beta\,\max(0,\,t-t_0)$.
- **Agent:** a LangGraph `StateGraph` with 11 nodes, `interrupt()`-based approval and SQLite checkpoints. LiteLLM provides model access (default `deepseek/deepseek-flash`; switching provider only means editing `.env`). The model returns JSON validated by Pydantic, with at most 2 repair attempts.
- **Guardrails in code, not just prompts:**
  - unknown citations trigger a repair, then are dropped;
  - *High* needs a verification result;
  - *Medium* or above needs evidence that directly shows the mechanism;
  - budgets of 20 MCP calls, 40 LLM calls and 3 verification rounds;
  - if the LLM fails, the case pauses and can resume from its checkpoint. No canned text is ever shown.
- **App:** FastAPI with Server-Sent Events, a React + TypeScript + ECharts workspace (English / Chinese) and Docker Compose.

## Challenges we ran into

- **Designing ambiguity on purpose.** Each scenario had to be statistically detectable but still need verification. Scenario C's apparent tester problem is really a product-mix shift with a missing reference sample. We added a "no-flip" rule (measurement noise never changes the pass/fail class of $z_{\text{true}} + b$) and searched seeds against the spec's own acceptance criteria.
- **Keeping the LLM honest.** Our first full evaluation put one Scenario C run at *Process deviation: Medium* based only on the failure-rate rise. We fixed it in code: every finding now carries a mechanism tag, and support of Medium or higher requires one. After that, all 9 runs ended in an acceptable conclusion.
- **New SDK versions.** MCP Python SDK 2.x renamed `FastMCP` to `MCPServer`, and LangGraph 1.x was new to us. We probed both APIs with small scripts before building on them.
- **Real bugs found by real runs:**
  - an SSE stream that never closed because one event followed `completed`;
  - a LangGraph node wrapper that returned a coroutine;
  - an over-long LLM answer that tested our retry-from-checkpoint path for us.

## Accomplishments

On 3 scenarios × 3 runs with the real DeepSeek API, scored against the hidden answer key:
- anomaly detection 9/9;
- acceptable conclusion 9/9;
- complete reports 9/9;
- citation validity 1.0;
- verification outcomes matching ground truth 1.0;
- about 1 minute and about US$0.012 per investigation.

The test suite has 66 deterministic tests, 11 frontend tests and 4 real-LLM tests. This is a small synthetic benchmark, not evidence of production-grade accuracy.

## What we learned

- Splitting the work so that **code computes and the model interprets** is what makes an industrial agent auditable.
- The most useful thing an assistant can say is often *"run this check next, and here is what each result would mean"*, not *"the root cause is X"*.
- Writing requirements first, including measurable acceptance criteria for the simulator, turned "make the demo convincing" into tests we could actually run.

## What's next

Connect real MES / QMS / test systems through MCP, add more failure modes (fixture wear, firmware changes, material lots), produce AI output in Chinese with matching guardrails, and add authentication for a hosted demo.

---

## 项目故事 – 中文版（参考用）

## 灵感来源

在汽车零部件工厂，EOL 下线测试是产品出厂前的最后一道关卡。当某台测试设备的不良率突然从约 2% 涨到约 18% 时，质量工程师必须尽快判断：产品真的坏了，还是测试设备测不准了，又或者只是这台设备上测的产品型号变了？

回答这个问题需要的数据分散在几个独立系统里：MES（订单、序列号、配方）、设备监控（拧紧扭矩、角度、程序版本）、EOL 测试（测量值、标准样件）。工程师只能导出表格、手工比对。真正代价高的不是少一张图表，而是过早下了一个笃定却错误的结论：要么报废好件，要么放行坏件。

多数"制造业 AI"演示止步于"解释可能发生了什么"。我们想做的助手还要说清**下一步该查什么**，等工程师批准后再执行，并在**证据变化时修正自己的判断**。

## 它做什么

Factory CSI 在一条虚构的产线（Alpha 工厂 A 线：ST-10 → ST-20 → ST-30 → EOL-A / EOL-B）上调查 EOL 质量异常：

1. **用统计方法发现异常**。对每台测试设备，比较班次最后 3 小时与前 2 小时：
   $$\text{flag}(t) \iff p_{\text{Fisher}}(t) < 0.01 \;\wedge\; r_{\text{window}}(t) \ge 2\cdot\max\big(r_{\text{baseline}}(t),\,0.5\%\big)$$
2. **通过 MCP 跨系统取证**。自建的工业 MCP 服务把模拟的 MES、设备、EOL 系统封装成 8 个工具，AI 的每次调用都实时显示在界面上。
3. **每个结论都有证据**。统计计算由确定性的 Python 代码完成，包括 Fisher、KS、Mann–Whitney 检验，OLS 趋势，按型号分层和型号构成变化。每个发现生成一条证据（如 `EV-007`），可以追溯到原始记录。AI 只能引用已有的证据编号。
4. **提出下一步最佳验证**。AI 给出最多 3 项排好序的模拟验证（换另一台设备交叉复测、标准样件检测、工艺配置核查），并说明每种结果会支持或否定哪个假设。
5. **人工确认**。工程师可以批准、全部拒绝（需写理由）或结束调查。批准的验证在模拟器中执行并返回新证据，AI 随后记录明确的判断变化，例如"测试设备漂移：中 → 高，依据 EV-019"。
6. **输出 10 个章节的可追溯报告**，包括时间线、证据、执行过的验证、判断变化和疑似受影响的产品范围。报告只使用"疑似"或"有证据支持"的措辞，从不写"已确认根因"。

## 如何构建

- **用 Kiro 做规格驱动开发**。我们写了 7 个 Spec，共 144 条 EARS 需求，并在写代码前做了一次跨 Spec 一致性检查。这次检查发现了真实的冲突：例如场景 C 的信号太弱，我们自己的检测规则根本触发不了；又如 LLM 调用上限设为 25 次时，最坏情况下只够跑一轮验证。Steering 文件记录关键规则：禁止兜底文本、标准答案隔离、引用规则。三个 Hook 分别在保存 Python 文件时跑相关测试和 ruff，在保存前端文件时跑 tsc 和 eslint，在每次保存时扫描密钥。同一个 MCP 服务也注册给了 Kiro 的开发 Agent 使用。
- **带隐藏真值的模拟器**。用固定随机种子为每个场景生成三份数据：
  - `factory.db`：可观测的业务系统数据；
  - `world_state.json`：隐藏的物理真值，只有验证引擎能读；
  - `ground_truth.json`：标准答案，只供测试和评测使用。

  import-linter 规则让后端和 MCP 服务在代码层面无法导入标准答案。测量采用归一化模型：
  $$z = \frac{v - m}{h},\qquad z_{\text{meas}} = z_{\text{true}} + b_{\text{tester}}(t) + \varepsilon,\quad \varepsilon \sim \mathcal{N}(0,\,0.1^2)$$
  其中 $m$ 为规格中值、$h$ 为半宽，$|z|\le 1$ 判为合格。测试设备漂移为 $b(t)=\beta\,\max(0,\,t-t_0)$。
- **Agent**：LangGraph 状态图共 11 个节点，用 `interrupt()` 实现人工审批，用 SQLite 保存检查点。模型通过 LiteLLM 接入（默认 `deepseek/deepseek-flash`，换模型只需改 `.env`），输出 JSON 并由 Pydantic 校验，最多修复 2 次。
- **护栏写在代码里，不只写在提示词里**：
  - 引用了不存在的证据，先要求修复，仍不合规则丢弃；
  - 支持度"高"必须有验证结果支撑；
  - "中"及以上必须有直接体现该机理的证据；
  - 预算上限为 MCP 调用 20 次、LLM 调用 40 次、验证 3 轮；
  - LLM 失败时案件暂停，可从检查点恢复，系统从不显示预设文本。
- **应用**：FastAPI 加 Server-Sent Events，React + TypeScript + ECharts 工作台（中英文界面），Docker Compose 一键启动。

## 遇到的挑战

- **刻意设计"模糊性"**。每个场景既要能被统计方法发现，又必须靠验证才能判断。场景 C 表面上像测试设备的问题，实际是型号构成变化，加上标准样件缺失。为此我们设计了"不翻转"规则（测量噪声不会改变 $z_{\text{true}} + b$ 的合格判定），并用 Spec 中的验收标准去搜索合适的随机种子。
- **让 LLM 保持诚实**。第一次完整评测中，场景 C 有一次仅凭不良率上升就给出了"工艺偏差：中"。我们在代码层面修复：每个发现都带有机理标签，支持度达到"中"或以上必须有对应机理的证据。修复后 9 次评测全部得到可接受的结论。
- **新版 SDK**。MCP Python SDK 2.x 把 `FastMCP` 改名为 `MCPServer`，LangGraph 1.x 对我们也是新的。我们先用小脚本探明这两套 API，再在上面开发。
- **真实运行发现的真实 bug**：
  - 因为 `completed` 事件之后还有一条事件，事件流一直不关闭；
  - LangGraph 节点包装函数返回了协程；
  - LLM 一次回答过长，正好让我们验证了"从检查点重试"这条路径。

## 取得的成果

用真实 DeepSeek API 跑 3 个场景各 3 次，对照隐藏的标准答案评分：
- 异常检测 9/9；
- 结论可接受 9/9；
- 报告完整 9/9；
- 证据引用有效率 1.0；
- 验证结果与真值一致率 1.0；
- 每次调查约 1 分钟，花费约 0.012 美元。

测试方面有 66 个确定性测试、11 个前端测试和 4 个真实 LLM 测试。这只是一个小型合成基准，不代表生产级的准确率。

## 学到了什么

- 让**代码负责计算、模型负责解释**，是工业 AI Agent 可审计的关键。
- 助手最有价值的一句话往往是"下一步做这项检查，每种结果分别意味着什么"，而不是"根因就是 X"。
- 先写需求，包括模拟器的可度量验收标准，把"让演示看起来可信"变成了可以真正运行的测试。

## 下一步

通过 MCP 接入真实的 MES、QMS 和测试系统，增加更多失效模式（夹具磨损、固件变更、物料批次），支持中文 AI 输出并配套相应的护栏，为在线演示加上身份认证。
