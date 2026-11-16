import { createContext, useContext, useState, type ReactNode } from "react";

export type Lang = "en" | "zh";

const zh: Record<string, string> = {
  // top bar
  "AI Manufacturing Quality Investigation Copilot": "AI 制造质量异常调查助手",
  "Factory Alpha · Line A": "Alpha 工厂 · A 线",
  SIMULATION: "模拟环境",
  Case: "案件",
  "— none —": "— 无 —",
  "LLM connected": "LLM 已连接",
  unavailable: "不可用",
  misconfigured: "配置错误",
  "Refresh LLM status": "刷新 LLM 状态",
  "LLM unavailable – AI investigation is disabled.": "LLM 不可用——AI 调查功能已禁用。",
  "Overview and statistics remain available.": "工厂总览与统计数据仍可使用。",
  Language: "语言",
  // factory panel
  Scenario: "场景",
  "Reset dataset": "重置数据",
  "Dataset reset": "数据已重置",
  "Reset dataset?": "确认重置数据？",
  "The simulated factory data is regenerated from its seed. All simulated verification records are removed. Investigation history stays.":
    "将按随机种子重新生成模拟工厂数据，并删除所有模拟验证记录；调查历史会保留。",
  Reset: "重置",
  Cancel: "取消",
  "Not possible while an investigation is active on this dataset": "该数据集有进行中的调查，不能重置",
  "Regenerate the dataset from its seed and remove simulated verification records": "按种子重新生成数据并删除模拟验证记录",
  "Factory overview": "工厂总览",
  "click a station": "点击工位查看",
  "Data range": "数据时间范围",
  Products: "产品数",
  "Overall FAIL_Rate": "总体不良率",
  Date: "日期",
  "(not generated)": "（未生成）",
  "Component assembly": "零部件装配",
  "Bolt tightening": "螺栓拧紧",
  "Functional assembly": "功能组装",
  "EOL tester A": "EOL 测试设备 A",
  "EOL tester B": "EOL 测试设备 B",
  Normal: "正常",
  Warning: "警告",
  Anomaly: "异常",
  Unknown: "未知",
  // workspace
  "Start Investigation": "开始调查",
  "Starting…": "启动中…",
  "Select a scenario and press Start Investigation.": "请选择场景并点击「开始调查」。",
  "LLM unavailable – AI investigation is disabled": "LLM 不可用——AI 调查功能已禁用",
  "Dataset not available": "数据集不可用",
  "An investigation is already active on this dataset": "该数据集已有进行中的调查",
  "Statistical detection (no investigation yet)": "统计检测结果（尚未调查）",
  "No anomaly detected in this dataset (last 3 h vs first 2 h).": "该数据集未检测到异常（最近 3 小时对比前 2 小时）。",
  "FAIL_Rate elevated": "不良率升高",
  baseline: "基线",
  window: "检测窗口",
  Trends: "趋势",
  bucket: "时间粒度",
  "FAIL_Rate by tester": "各测试设备不良率",
  "ST-20 tightening angle": "ST-20 拧紧角度",
  "Reference deviation": "标准样件偏差",
  "Evidence timeline": "证据时间线",
  "No timeline yet — events appear as evidence is collected.": "暂无时间线——收集证据后会自动出现。",
  Load: "加载",
  Detect: "检测",
  Collect: "收集",
  Analyze: "分析",
  Hypotheses: "假设",
  Propose: "建议",
  Approval: "审批",
  Verify: "验证",
  Update: "更新",
  Report: "报告",
  "Computed data": "计算数据",
  "Source records": "原始记录",
  "This evidence item has no source record references.": "该证据没有关联的原始记录。",
  simulation: "模拟",
  "First tests": "首次测试",
  Fails: "不合格",
  "Reference sample checks": "标准样件检测",
  "Recent failures": "最近不合格",
  "Process changes": "工艺变更",
  "Equipment events": "设备事件",
  "Process steps in data range": "数据范围内的加工工序数",
  "Related evidence in this case": "本案件中的相关证据",
  "No related evidence (start an investigation first).": "暂无相关证据（请先开始调查）。",
  None: "无",
  // investigator
  "AI Investigator": "AI 调查员",
  "No investigation yet — select a scenario and press Start Investigation.": "尚无调查——请选择场景并点击「开始调查」。",
  Status: "状态",
  Node: "节点",
  Round: "轮次",
  "MCP calls": "MCP 调用",
  "LLM calls": "LLM 调用",
  tokens: "tokens",
  "MCP tool calls": "MCP 工具调用",
  "No tool calls yet.": "暂无工具调用。",
  "call id": "调用 ID",
  result: "结果",
  bytes: "字节",
  "Collected evidence": "已收集证据",
  "No evidence yet.": "暂无证据。",
  "Evidence support": "证据支持度",
  Supporting: "支持证据",
  Contradicting: "反对证据",
  "Missing evidence": "缺失证据",
  none: "无",
  "Next Best Verification": "下一步最佳验证",
  "final round of suggestions": "最后一轮建议",
  "proposal round": "建议轮次",
  "No valid verification proposal.": "没有有效的验证建议。",
  "AI suggests concluding:": "AI 建议结束调查：",
  simulated: "模拟",
  "If outcome": "如果结果为",
  Hypothesis: "假设",
  supports: "支持",
  contradicts: "反对",
  neutral: "中性",
  "Approve Verification": "批准验证",
  "Show top suggestion only": "只看首选建议",
  "Show other suggestions": "查看其他建议",
  "Reject all": "全部拒绝",
  left: "次剩余",
  "Reject limit reached (2 per case)": "已达拒绝次数上限（每案 2 次）",
  "Decision submitted": "决策已提交",
  "Conclude Investigation": "结束调查",
  "Reason for rejecting all suggestions (required, ≤500 characters)": "拒绝全部建议的理由（必填，≤500 字）",
  "Reject all suggestions": "拒绝全部建议",
  "Conclude the investigation?": "确认结束调查？",
  "No further verification will run. The AI writes the final conclusion and the report from the current evidence.":
    "不再执行新的验证。AI 将根据现有证据撰写最终结论和报告。",
  Conclude: "结束",
  "Judgment changes": "判断变化",
  round: "第",
  because: "依据",
  removed: "已移除",
  Conclusion: "结论",
  "Open report": "打开报告",
  "Simulated data · decision support · not a certified root cause.": "模拟数据 · 辅助决策 · 不是经过认证的根因。",
  "Investigation paused: LLM failure": "调查暂停：LLM 调用失败",
  "Investigation failed": "调查失败",
  "LLM unavailable – retry is disabled": "LLM 不可用——无法重试",
  "Retry from last checkpoint": "从上一个检查点重试",
  "Dropped invalid citation(s)": "已丢弃无效引用",
  "Budget exhausted": "预算已用尽",
  "A proposal was rejected by the validator": "一条建议被校验器拒绝",
  // report page
  Workspace: "工作台",
  "Investigation Report": "调查报告",
  "Download Markdown": "下载 Markdown",
  "Print / Save as PDF": "打印 / 保存为 PDF",
  "Short-form report": "简版报告",
  sections: "个章节",
  "Report content is generated in English.": "报告正文为英文生成。",
  // categories / verification types / labels
  "Tester measurement drift": "测试设备测量漂移",
  "Process parameter deviation": "工艺参数偏差",
  "Product mix shift": "产品构成变化",
  "Material lot issue": "物料批次问题",
  "Insufficient evidence": "证据不足",
  "Cross retest": "交叉复测",
  "Reference sample check": "标准样件检测",
  "Process configuration check": "工艺配置核查",
  High: "高",
  Medium: "中",
  Low: "低",
  Insufficient: "不足",
  "Evidence-supported cause": "有证据支持的疑似原因",
  "Suspected cause": "疑似原因",
  "Insufficient evidence for a conclusion": "证据不足，无法下结论",
  // scenario registry (labels come from the backend in English)
  "Baseline – Normal Operation": "基线 – 正常运行",
  "Scenario A – EOL Tester Drift": "场景 A – EOL 测试设备漂移",
  "Scenario B – Manufacturing Process Defect": "场景 B – 制造工艺缺陷",
  "Scenario C – Insufficient Evidence": "场景 C – 证据不足",
  "One normal 8-hour shift on Line A with about 2% EOL defects on both testers.": "A 线一个正常的 8 小时班次，两台测试设备的 EOL 不良率约 2%。",
  "EOL Tester B defect rate climbs during the shift while Tester A stays normal.": "班次中 EOL 测试设备 B 的不良率持续上升，测试设备 A 保持正常。",
  "Both EOL testers report more defects in the second half of the shift.": "班次后半段两台 EOL 测试设备的不良都明显增加。",
  "EOL Tester B shows a higher defect rate, but key verification data is missing.": "EOL 测试设备 B 不良率偏高，但缺少关键的验证数据。",
  // equipment status reason codes
  ANOMALY_DETECTED: "不良率显著升高（统计检测）",
  REFERENCE_CHECK_FAILED: "标准样件检测超差",
  FAIL_RATE_RISING: "最近 60 分钟不良率 ≥ 基线 2 倍",
  ALARM_RECENT: "最近 60 分钟有报警",
  PARAMETER_SHIFT_AFTER_CHANGE: "程序变更后拧紧角度分布发生变化",
};

const DICTS: Record<Lang, Record<string, string>> = { en: {}, zh };

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (s: string) => string };
const I18nContext = createContext<Ctx>({ lang: "en", setLang: () => {}, t: (s) => s });

function initialLang(): Lang {
  try {
    const q = new URLSearchParams(window.location.search).get("lang");
    if (q === "zh" || q === "en") return q;
    const v = localStorage.getItem("fcsi.lang");
    if (v === "zh" || v === "en") return v;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

export function I18nProvider({ children, lang: forced }: { children: ReactNode; lang?: Lang }) {
  const [lang, setLangState] = useState<Lang>(forced ?? initialLang());
  const setLang = (l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("fcsi.lang", l);
    } catch {
      /* ignore */
    }
    document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
  };
  const t = (s: string) => DICTS[lang][s] ?? s;
  return <I18nContext.Provider value={{ lang, setLang, t }}>{children}</I18nContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export const useI18n = () => useContext(I18nContext);

/** Missing-key helper for tests. */
// eslint-disable-next-line react-refresh/only-export-components
export const ZH_KEYS = Object.keys(zh);
