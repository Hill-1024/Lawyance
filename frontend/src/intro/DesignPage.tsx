/*
 * 系统架构与设计页：自 lawyance-intro 的 DesignPage.vue 逐段移植。
 * 模板结构与中文文案保持原文；页头/页脚由应用布局提供，此处不包含。
 * 对应样式见 intro-design.css（原 Vue 单文件样式按 app token 映射后移植）。
 */

import { useRef } from "react";
import type { CSSProperties } from "react";
import { Box, LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";
import { useAmbientBackground } from "./effects";
import "./intro-design.css";

// 首屏元素沿用 Vue 模板里的显式 --delay 入场延迟，这里原样保留。
const delay = (ms: number) => ({ "--delay": `${ms}ms` }) as CSSProperties;

export default function DesignPage() {
  // 沙箱安全节是整页唯一的深色横幅：它充满视口时驱动整页背景随之变暗。
  const securityRef = useRef<HTMLElement>(null);
  useAmbientBackground(securityRef);

  return (
    <main id="top" className="page intro-page--design" aria-labelledby="design-hero-title">
      {/* Hero Section */}
      <section className="hero design-hero" aria-labelledby="design-hero-title">
        <div className="hero__content">
          <span className="hero__tag reveal is-visible" style={delay(80)}>ARCHITECTURAL DESIGN</span>
          <h1 id="design-hero-title" className="reveal is-visible" style={delay(160)}>系统架构与设计</h1>
          <p className="hero__lead reveal is-visible" style={delay(240)}>
            Lawver 绝非不可追溯结论的「黑盒对话框」，而是一套将法律推理、分步规划、独立记忆、隔离沙箱与输出校验收束在同一物理边界内的专业级工作台。
          </p>
          <nav className="hero-index reveal is-visible" style={delay(320)} aria-label="本页章节">
            <a href="#topology"><span>01</span>整体拓扑</a>
            <a href="#pipeline"><span>02</span>编排管线</a>
            <a href="#court"><span>03</span>模拟法庭</a>
            <a href="#memory"><span>04</span>记忆系统</a>
            <a href="#security"><span>05</span>沙箱边界</a>
          </nav>
        </div>
      </section>

      {/* Component 1: Overall Topology & MCPS */}
      <section id="topology" className="section section--design" aria-labelledby="topo-title">
        <div className="section__heading reveal">
          <p>01 / 整体拓扑与工具隔离</p>
          <h2 id="topo-title">统一网关转发，工具可见性严格控制。</h2>
        </div>

        <div className="design-content reveal">
          <p className="section-lead-paragraph">
            Lawver 采用分层的微服务架构。前端基于 React 19 / Vite 提供沉浸式聊天、模拟法庭和工作区控制；后端使用 FastAPI 构建，通过统一的 <code>mcps.py</code> 工具转发层，将所有底层能力以 Model Context Protocol (MCP) 规约暴露给 Agent 编排层。
          </p>

          {/* Premium Architecture Diagram */}
          <div className="topo-stack reveal">
            <article className="topo-row">
              <div className="topo-row__head">
                <span>01</span>
                <h4>UI 展现层</h4>
                <p>React 19 / Tailwind / Capacitor</p>
              </div>
              <div className="topo-row__nodes">
                <span className="node-chip">主聊天工作台</span>
                <span className="node-chip">模拟法庭控制</span>
                <span className="node-chip">文件沙箱管理器</span>
              </div>
            </article>

            <p className="topo-connector">REST API / SSE Streams / File Transfer</p>

            <article className="topo-row">
              <div className="topo-row__head">
                <span>02</span>
                <h4>应用服务层</h4>
                <p>FastAPI Application &amp; App Factory</p>
              </div>
              <div className="topo-row__nodes">
                <span className="node-chip">会话生命周期</span>
                <span className="node-chip">记忆同步引擎</span>
                <span className="node-chip">OCP 格式审查器</span>
              </div>
            </article>

            <p className="topo-connector">Agent 任务分发（Orchestrator）</p>

            <article className="topo-row topo-row--accent">
              <div className="topo-row__head">
                <span>03</span>
                <h4>统一工具转发层</h4>
                <p>MCPS Core Protocol</p>
              </div>
              <div className="topo-row__nodes">
                <span className="node-chip">agent（主问答）</span>
                <span className="node-chip">court（庭审专属）</span>
                <span className="node-chip">ocp_reviewer（审查）</span>
                <span className="node-chip">internal（内部调用）</span>
              </div>
            </article>

            <p className="topo-connector">底层协议适配器（MCP Client Adapters）</p>

            <article className="topo-row">
              <div className="topo-row__head">
                <span>04</span>
                <h4>底层引擎与信源</h4>
                <p>Local / Remote Engine Services</p>
              </div>
              <div className="topo-row__nodes">
                <span className="node-chip">法库 RAG</span>
                <span className="node-chip">SearXNG 联网</span>
                <span className="node-chip">企业工商查询</span>
                <span className="node-chip">文档批注处理器</span>
              </div>
            </article>
          </div>

          <div className="features-grid">
            <div className="feature-card">
              <h3>统一网关 (MCPS Gateway)</h3>
              <p>业务工具（无论是本地数据库还是远程第三方接口）统一通过 <code>mcps.py</code> 转发，严禁 Agent 或接口层绕过网关直接调用，从而确保完整的权限审计和隔离能力。</p>
            </div>
            <div className="feature-card">
              <h3>工具可见性隔离 (Exposure Settings)</h3>
              <p>每个工具都声明其 <code>exposure</code>。如企业工商和法条检索仅在 <code>agent</code> 或 <code>court</code> 可见；而高权限系统控制仅在 <code>internal</code> 或 <code>plan_and_solve</code> 可见，限制了越权风险。</p>
            </div>
          </div>
        </div>
      </section>

      {/* Component 2: Dual-Track Pipelines */}
      <section id="pipeline" className="section section--design" aria-labelledby="pipeline-title">
        <div className="section__heading reveal">
          <p>02 / 智能体编排与输出审查</p>
          <h2 id="pipeline-title">双轨决策，输出多级审查净化。</h2>
        </div>

        <div className="design-content reveal">
          <p className="section-lead-paragraph">
            Lawver 支持 <strong>Direct Mode（默认问答）</strong> 和 <strong>Plan-and-Solve（规划求解）</strong> 两套决策管线，分别应对日常即时咨询与多请求、长链路深度案件分析。
          </p>

          <div className="pipeline-flow">
            <div className="pipeline-track">
              <div className="track-header">管线 A：Direct Mode (默认咨询)</div>
              <div className="track-step">1. 接收请求与当前对话上下文</div>
              <div className="track-step">2. 注入对话记忆、焦点提示词与可用工具元数据</div>
              <div className="track-step">3. 循环调用工具进行信息确认 (RAG/工商/搜索)</div>
              <div className="track-step">4. 组织事实与法律依据生成初稿</div>
            </div>

            <div className="pipeline-track pipeline-track--solve">
              <div className="track-header">管线 B：Plan &amp; Solve (规划求解)</div>
              <div className="track-step">1. 输入复杂复合型诉求 / 长篇案卷</div>
              <div className="track-step">2. 编排器拆解生成结构化步骤计划 (Plan)</div>
              <div className="track-step">3. 逐项推进，每步调用特定子工具并生成中间结果</div>
              <div className="track-step">4. 汇总多步报告，避免超长逻辑中途偏离焦点</div>
            </div>
          </div>

          {/* Output Checking Process */}
          <div className="ocp-section reveal">
            <div className="ocp-banner">
              <div className="ocp-badge">OCP</div>
              <h3>Output Check Process (输出审查流水线)</h3>
            </div>
            <p>
              当主生成模型生成法律文书或意见后，回复不直接投递给前端，而是拦截并进入独立的 <strong>Output Check Process (OCP)</strong>：
            </p>
            <div className="ocp-steps">
              <div className="ocp-step-card">
                <span className="step-no">01</span>
                <h4>合规性与引用审查</h4>
                <p>由独立的 OCP 审查器读取原始输出，调用 <code>ocp_reviewer</code> 级别只读信源工具，逐一核验正文引用的法条和案例是否真实存在，并在正文追加带有链接的核准角标。</p>
              </div>
              <div className="ocp-step-card">
                <span className="step-no">02</span>
                <h4>格式与渲染审查</h4>
                <p>强制检查 Markdown 表格格式、引用角标格式及输出结构一致性，对破损或不规范的格式进行纠错。</p>
              </div>
              <div className="ocp-step-card">
                <span className="step-no">03</span>
                <h4>Sanitizer 容错保护</h4>
                <p>若审查模型发生超时、网络或逻辑异常，系统将自动触发 <strong>Deterministic Sanitizer Fallback</strong>。该机制采用确定性纯正则表达式和解析器对正文进行安全净化，抛弃异常，保留主模型原始输出，确保链路高可用。</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Component 3: Mock Court */}
      <section id="court" className="section section--design" aria-labelledby="court-title">
        <div className="section__heading reveal">
          <p>03 / 多智能体模拟法庭</p>
          <h2 id="court-title">有限状态机编排，四角色物理隔离记忆。</h2>
        </div>

        <div className="design-content reveal">
          <p className="section-lead-paragraph">
            模拟法庭是 Lawver 的一项核心工程突破。它不仅是一个简单的多人对话，而是一个由 <strong>有限状态机 (FSM)</strong> 驱动、严格隔离各方信息差的模拟庭审对抗环境。
          </p>

          {/* FSM Stage visualization */}
          <div className="fsm-visual reveal">
            <h4>庭审有限状态机流程 (FSM States)</h4>
            <div className="fsm-rail">
              <div className="fsm-stage"><span>01</span><strong>开庭准备</strong></div>
              <div className="fsm-stage"><span>02</span><strong>诉辩陈述</strong></div>
              <div className="fsm-stage"><span>03</span><strong>法庭调查</strong></div>
              <div className="fsm-stage"><span>04</span><strong>举证质证</strong></div>
              <div className="fsm-stage"><span>05</span><strong>法庭辩论</strong></div>
              <div className="fsm-stage"><span>06</span><strong>庭审复盘</strong></div>
            </div>
            <p className="fsm-meta">支持 <strong>民事、行政、刑事</strong> 三类基础案由状态流转，各阶段拥有明确的进入和退出条件。</p>
          </div>

          <div className="court-roles reveal">
            <div className="role-grid">
              <div className="role-card">
                <div className="role-icon font-serif">审</div>
                <h4>审判长 (Judge)</h4>
                <p>维持庭审秩序，引导诉辩双方推进状态机，主持举证和辩论，并最终出具中立客观的法庭裁判意见。</p>
              </div>
              <div className="role-card">
                <div className="role-icon font-serif">诉</div>
                <h4>对方代理人 (Opponent)</h4>
                <p>扮演模拟庭审中的抗辩对手，根据其私有 Brief 发掘漏洞，提出假设抗辩点，对用户进行压力测试。</p>
              </div>
              <div className="role-card">
                <div className="role-icon font-serif">助</div>
                <h4>我方 AI 助手 (User Agent)</h4>
                <p>辅助用户进行分析，提供实时的法条依据和策略参考，引导用户有针对性地发言。</p>
              </div>
              <div className="role-card">
                <div className="role-icon font-serif">评</div>
                <h4>庭后复盘员 (Reviewer)</h4>
                <p>在庭审结束后，全盘审视所有发言，结合各方底牌分析得失，生成多维度复盘与改进建议。</p>
              </div>
            </div>
          </div>

          <div className="trust-grid reveal">
            <div className="trust-card">
              <h4>四角色私有记忆隔离</h4>
              <p>为防止 AI 角色在生成回复时「作弊」，系统为 Judge、Opponent、Reviewer 和 User Agent 分配了独立的记忆作用域 (Memory Scopes)。公开案卷和庭审笔录写入共享存储，而各自的诉讼策略、底牌 brief 隔离在各自私有空间，不可跨域读取。</p>
            </div>
            <div className="trust-card">
              <h4>回退与派生分支 (Branching &amp; Rollback)</h4>
              <p>系统记录了庭审的完整事件链。用户可以随时将状态机回退到任意已发生的发言节点，清空该节点之后的 AI 私有记忆，重新推进；也可以从当前节点派生出一条全新的平行会话分支，进行多套策略对比测试。</p>
            </div>
          </div>
        </div>
      </section>

      {/* Component 4: Context & Memory System */}
      <section id="memory" className="section section--design" aria-labelledby="memory-title-design">
        <div className="section__heading reveal">
          <p>04 / 多路召回记忆系统</p>
          <h2 id="memory-title-design">拒绝暴力拼接历史，通过语义多路融合提取关键。</h2>
        </div>

        <div className="design-content reveal">
          <p className="section-lead-paragraph">
            传统的 AI 助手往往通过暴力拼接全部对话历史来保持记忆，这不仅导致上下文极度臃肿，且容易引入过期和矛盾的事实。Lawver 设计了基于多路召回排序的<strong>对话级结构化记忆系统</strong>。
          </p>

          <div className="memory-retrieval">
            <div className="retrieval-channels">
              <div className="channel-card">
                <span>Channel 1</span>
                <h4>关键词精准匹配</h4>
                <p>捕获当前问题中核心法律术语及事实要素的硬字词频率。</p>
              </div>
              <div className="channel-card">
                <span>Channel 2</span>
                <h4>实体与语义标签</h4>
                <p>通过 NER 技术抽取出当事人、主体、争议标的物等稳定标签关系。</p>
              </div>
              <div className="channel-card">
                <span>Channel 3</span>
                <h4>时序与动态衰减</h4>
                <p>根据记忆产生的时间戳，对历史交互事实应用平滑衰减，优先保障新鲜度。</p>
              </div>
              <div className="channel-card">
                <span>Channel 4</span>
                <h4>向量 Embedding 相似度</h4>
                <p>可按需配置启用基于 Dense Vector 的语义距离相似度计算，作为 RAG 排序的召回因子之一。</p>
              </div>
            </div>

            <div className="retrieval-fusion">
              <div className="fusion-box">
                <span>融合排序引擎 (RAG Multi-Route Fusion &amp; Reranking)</span>
                <p>各路召回信号通过预设的超参权重矩阵合并，输出当前最迫切需要关注的「目标、约束与事实边界」，并在每轮请求前动态注入 System Message，保持上下文的轻量与高效。</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Component 5: Sandbox & Security. The dark band wraps the column instead of
          being the column, so its fade spans the viewport rather than stopping at
          the 1180px content width. */}
      <section id="security" className="band--dark" ref={securityRef} aria-labelledby="sec-title">
        <div className="section section--design">
          <div className="section__heading reveal">
            <p>05 / 沙箱边界与系统安全</p>
            <h2 id="sec-title">事实先于承诺，数据逻辑物理强隔离。</h2>
          </div>

          <div className="design-content reveal">
            <p className="section-lead-paragraph">
              我们秉持「安全边界先于产品承诺」的原则，为涉案敏感材料、上传文件与代码执行环境构筑了严密的底层护城河。
            </p>

            <div className="security-features">
              <div className="sec-card">
                <div className="sec-icon">
                  <LockKeyhole aria-hidden="true" strokeWidth={1.75} />
                </div>
                <h4>工作区物理强隔离</h4>
                <p>所有上传的文件卷宗和生成的报告文书，严格按照用户 ID 及会话 Session ID 隔离存放在 <code>TEMP</code> 与 <code>Result</code> 文件夹中。通过 <code>workspace.py</code> 校验核心读写路径，从根本上防止跨会话的目录遍历漏洞（Path Traversal）。</p>
              </div>

              <div className="sec-card">
                <div className="sec-icon">
                  <Box aria-hidden="true" strokeWidth={1.75} />
                </div>
                <h4>可信源控制与输入审查</h4>
                <p>联网检索工具 SearXNG 及网页文本阅读器对抓取内容做只读与「不可信」标记，禁止对抓取的内容进行代码级运行与指令执行。同时对外部 REST 接口启用 CORS 回环验证和 IP 限流保护。</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Footer / CTA */}
      <section className="final design-final">
        <h2 className="reveal">致力于构建严谨、可追溯且高度安全的法律科技。</h2>
        <p className="reveal">Lawver 持续优化其编排流程，努力在专业法律场景中为您提供最坚实的决策辅助支持。</p>
        <div className="final__cta-group reveal" style={delay(160)}>
          <Link to="/" className="primary-cta">返回产品首页</Link>
          <Link to="/download" className="secondary-cta">前往下载中心</Link>
        </div>
      </section>
    </main>
  );
}
