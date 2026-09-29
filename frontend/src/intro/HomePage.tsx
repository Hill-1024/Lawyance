/*
 * 模块描述：介绍页首页（自 HomePage.vue 移植）。
 * Hero 采用 quote.law 版式：发布徽章 pill + 超大宋体标题 + 一行副标题 + CTA 对，
 * 标题文案与工作台新会话页同源（「让法律工作，井然有序。」），保证产品连续性。
 * 内容区块（能力/工作台/工作方式/记忆/边界）沿用官网既有叙事。
 */

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import WorkbenchDemo from "./WorkbenchDemo";
import { useAmbientBackground } from "./effects";

interface HomePageProps {
  isAuthenticated: boolean;
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

const ABILITIES = [
  {
    no: "01",
    title: "法律与案例检索",
    body: "查询法律法规、司法解释、来源链接和相似案例；联网搜索只补充公开网页材料，法律依据优先回到可核验信源。",
  },
  {
    no: "02",
    title: "企业与主体信息",
    body: "接入企业简介、工商登记、股东、主要人员、联系方式、上市信息和对外投资查询，帮助商业法律问题先确认主体与背景。",
  },
  {
    no: "03",
    title: "卷宗与文档处理",
    body: "读取 PDF / Word 原文，支持 PDF 句级坐标批注、Word 段落批注、工作区文件清点与生成结果回写，避免附件在不同会话间串线。",
  },
  {
    no: "04",
    title: "模拟法庭训练",
    body: "支持民事、行政、刑事庭审流程，让法官、对方律师、复盘员与我方代理围绕公开案卷和私有作战笔记进行压力测试。",
  },
  {
    no: "05",
    title: "咨询与输出审查",
    body: "默认咨询保持直接，复杂任务先规划再逐步执行；输出前可审查结构、引用、表格和表达一致性。",
  },
];

const WORK_SURFACES = [
  {
    no: "Consult",
    title: "法律咨询工作台",
    body: "对话、文件、上下文用量、工作区和生成结果在同一界面中保持同步，适合从事实整理一路推进到法律意见初稿。",
    points: ["对话分叉、撤回、编辑与重新生成", "上传文件、生成文件与本地缓存同步", "从引用材料继续追问，将成果保存在工作环境中"],
  },
  {
    no: "Court",
    title: "模拟法庭工作台",
    body: "用公开案卷建立共同事实，用私有作战笔记保留策略；不同 AI 角色拥有隔离记忆，庭审记录持续沉淀为可复盘的时间线。",
    points: ["民事、行政、刑事三类庭审入口", "法官、对方律师、复盘员和我方代理分工", "插话、撤回、分支、角色记忆清理与 OCP 复盘"],
  },
];

const WORKFLOW = [
  {
    no: "Default",
    phase: "Direct",
    title: "默认咨询",
    body: "默认模式接收问题、同步必要记忆、调用可见工具并形成答复，适合事实边界清楚的咨询和文档问答。",
    details: [
      { label: "适用", value: "明确、边界清晰的法律问题" },
      { label: "动作", value: "直接组织事实、依据与结论" },
    ],
  },
  {
    no: "Plan",
    phase: "Plan & Solve",
    title: "分步完成复杂任务",
    body: "复杂任务先提交结构化计划，再逐步执行和汇总，避免多请求、多事实、多工具任务在中途失焦。",
    details: [
      { label: "适用", value: "多事实、多请求、长链路分析" },
      { label: "动作", value: "先形成步骤，再逐项推进" },
    ],
  },
  {
    no: "OCP",
    phase: "Review",
    title: "核验依据与表达",
    body: "审查正文结构、引用角标和 Markdown 表格，必要时补充法规信源并应用修正版。",
    details: [
      { label: "适用", value: "输出前的结构与信源校验" },
      { label: "动作", value: "检查引用、表格与表达一致性" },
    ],
  },
];

const MEMORY_ITEMS = [
  {
    no: "01",
    title: "自动注入",
    body: "当前焦点和高优先级约束会在每轮生成前进入上下文，避免依赖模型主动想起。",
  },
  {
    no: "02",
    title: "多路召回",
    body: "当问题依赖早先事实且当前上下文不足时，通过关键词、实体、语义标签、时序、优先级与可选 embedding 信号召回。",
  },
  {
    no: "03",
    title: "作用域隔离",
    body: "普通咨询使用对话级记忆；模拟法庭为法官、对方律师、复盘员和我方代理分配独立角色记忆，避免私有信息直接串场。",
  },
];

const TRUST_ITEMS = [
  {
    no: "A",
    title: "资料在哪里保存",
    body: "项目、文档与会话持久保存在服务端，按账号隔离；浏览器只保留缓存与草稿。换设备登录即可继续。",
  },
  {
    no: "B",
    title: "本次明确引用",
    body: "材料进入任务前应由你明确选择。使用外部模型或插件时，所需内容会发送到相应服务处理；请结合机构要求选择服务与上传材料。",
  },
  {
    no: "C",
    title: "保留原文与版本",
    body: "原始附件完整保留。AI 修改先提出建议，由你审阅后接受；文档保存会产生版本，发生冲突时保留双方内容。",
  },
  {
    no: "D",
    title: "产品与服务边界",
    body: "账号与套餐由客服一对一开通，不开放自助注册。AI 输出不能代替对事实和法律依据的专业核验。",
  },
];

export default function HomePage({ isAuthenticated }: HomePageProps) {
  const trustRef = useRef<HTMLElement>(null);
  const methodRef = useRef<HTMLElement>(null);
  const [activeWorkflowIndex, setActiveWorkflowIndex] = useState(0);

  useAmbientBackground(trustRef);

  useEffect(() => {
    document.title = "Lawver | 法律 AI 工作台";
  }, []);

  // 方法卡堆：由 section 滚动进度推导当前卡（rAF 节流），逻辑与官网一致。
  const methodFrame = useRef(0);
  useEffect(() => {
    const measure = () => {
      const method = methodRef.current;
      if (!method) return 0;
      const rect = method.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      const scrollable = Math.max(1, rect.height - viewportHeight);
      const progress = clamp01((viewportHeight * 0.18 - rect.top) / scrollable);
      return Math.min(WORKFLOW.length - 1, Math.floor(progress * WORKFLOW.length));
    };
    const update = () => {
      if (methodFrame.current) return;
      methodFrame.current = window.requestAnimationFrame(() => {
        methodFrame.current = 0;
        setActiveWorkflowIndex(measure());
      });
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      if (methodFrame.current) window.cancelAnimationFrame(methodFrame.current);
    };
  }, []);

  const startCtaTo = isAuthenticated ? "/home" : "/login";

  return (
    <main id="top" className="page">
      <section className="hero hero--display" aria-labelledby="hero-title">
        <div className="hero__content">
          <Link to="/download" className="hero__badge reveal">
            服务条款与定价已公布
            <span aria-hidden="true">→</span>
          </Link>
          <h1 id="hero-title" className="reveal">
            让法律工作，
            <br />
            井然有序。
          </h1>
          <p className="hero__lead reveal">
            从整理材料到形成文书，从核验依据到准备庭审。Lawver 让每一步法律工作，都有清晰的上下文与可继续追问的结果。
          </p>
          <div className="hero__action reveal">
            <div className="hero__cta-group">
              <Link to={startCtaTo} className="primary-cta">
                <span>开始使用</span>
              </Link>
              <Link to="/download" className="secondary-cta">
                <span>下载客户端</span>
              </Link>
            </div>
          </div>
        </div>
      </section>

      <WorkbenchDemo />

      <section id="abilities" className="section section--abilities" aria-labelledby="abilities-title">
        <div className="section__heading reveal">
          <p>能力介绍</p>
          <h2 id="abilities-title">从真实法律工作出发，先处理事实，再组织依据。</h2>
        </div>
        <div className="text-rows" aria-label="Lawver 能力">
          {ABILITIES.map((item) => (
            <article key={item.title} className="text-row reveal">
              <span>{item.no}</span>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="workbench" className="section workbench" aria-labelledby="workbench-title">
        <div className="section__heading reveal">
          <p>应用工作台</p>
          <h2 id="workbench-title">咨询、卷宗与庭审训练，沿着同一条案件线索展开。</h2>
        </div>
        <div className="workbench__layout" aria-label="核心工作台">
          {WORK_SURFACES.map((surface) => (
            <article key={surface.title} className="surface-pane reveal">
              <div className="surface-pane__heading">
                <span>{surface.no}</span>
                <h3>{surface.title}</h3>
              </div>
              <p>{surface.body}</p>
              <ul>
                {surface.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section
        id="method"
        ref={methodRef}
        className="section method"
        aria-labelledby="method-title"
        style={{ "--workflow-count": WORKFLOW.length } as React.CSSProperties}
      >
        <div className="method__sticky">
          <div className="method__copy reveal">
            <p>工作方式</p>
            <h2 id="method-title">先厘清问题，再形成可以核验的答案。</h2>
            <p>
              Lawver 在不同任务复杂度下切换工作方式。简单咨询保持直接，复杂任务先明确步骤。
              引用能回到来源，结论能说明依据，未核实的信息也应如实标注。
            </p>
            <div className="method__progress" aria-hidden="true">
              {WORKFLOW.map((step, index) => (
                <span key={step.no} className={index === activeWorkflowIndex ? "is-current" : ""} />
              ))}
            </div>
          </div>
          <div className="agent-stack" aria-label="Lawver 工作方式">
            {WORKFLOW.map((step, index) => (
              <article
                key={step.title}
                className={
                  "agent-card" +
                  (index === activeWorkflowIndex ? " is-active" : "") +
                  (index < activeWorkflowIndex ? " is-before" : "") +
                  (index > activeWorkflowIndex ? " is-after" : "")
                }
                style={
                  {
                    "--card-index": index,
                    "--card-offset": index - activeWorkflowIndex,
                  } as React.CSSProperties
                }
              >
                <div className="agent-card__meta">
                  <span>{step.no}</span>
                  <span>{step.phase}</span>
                </div>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </div>
                <dl className="agent-card__details">
                  {step.details.map((detail) => (
                    <div key={detail.label}>
                      <dt>{detail.label}</dt>
                      <dd>{detail.value}</dd>
                    </div>
                  ))}
                </dl>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="memory" className="section memory" aria-labelledby="memory-title">
        <div className="section__heading reveal">
          <p>注意力与记忆</p>
          <h2 id="memory-title">注意力处理当下，记忆保留边界。</h2>
        </div>
        <div className="memory__body">
          <p className="memory__lead reveal">
            Lawver 不把所有历史都压进当前上下文，也不把记忆做成用户画像。系统先让当前问题、卷宗片段与工具结果进入注意力，
            再把对话级记忆或庭审角色记忆中稳定的目标、约束与案件事实作为边界补入。
          </p>
          <div className="memory__balance reveal" aria-label="注意力与记忆的平衡">
            <article className="memory-pane">
              <span>Attention</span>
              <h3>当前注意力</h3>
              <p>聚焦本轮问题、用户最新修正、检索结果和正在审查的文档，让回答先对齐眼前事实。</p>
            </article>
            <div className="memory__bridge" aria-hidden="true">
              <span></span>
              <strong>Balance</strong>
              <span></span>
            </div>
            <article className="memory-pane memory-pane--teal">
              <span>Memory</span>
              <h3>对话级记忆</h3>
              <p>保留稳定目标、高优先级约束、案件事实和工作边界，在需要时帮助模型回到已确认的信息。</p>
            </article>
          </div>
          <div className="memory__rows">
            {MEMORY_ITEMS.map((item) => (
              <article key={item.title} className="memory-row reveal">
                <span>{item.no}</span>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="trust" ref={trustRef} className="trust" aria-labelledby="trust-title">
        <div className="trust__inner">
          <div className="trust__heading reveal">
            <p>信任与边界</p>
            <h2 id="trust-title">数据边界先于产品承诺。</h2>
          </div>
          <div className="trust__items">
            {TRUST_ITEMS.map((item) => (
              <article key={item.title} className="trust-item reveal">
                <span>{item.no}</span>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="consultation" className="final" aria-labelledby="final-title">
        <h2 id="final-title" className="reveal">
          让法律咨询回到事实、条文与可验证的表达。
        </h2>
        <p className="reveal">Lawver 保持安静的界面和谨慎的语言，只在必要处提供结构、依据与下一步。</p>
        <div className="final__cta-group reveal" style={{ "--delay": "200ms" } as React.CSSProperties}>
          <Link to={startCtaTo} className="primary-cta">
            打开工作台
          </Link>
          <Link to="/download" className="secondary-cta">
            下载 Android 应用
          </Link>
        </div>
      </section>
    </main>
  );
}
