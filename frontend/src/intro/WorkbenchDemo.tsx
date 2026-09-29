/*
 * 模块描述：介绍页「交互体验」区块——纯前端虚构材料演示（自 WorkbenchDemo.vue 移植）。
 * 划选条款 → 询问修改 → 生成内联删除线/替换预览 → 接受或拒绝 → 版本 2。
 * 不上传内容、不调用模型；配色走 app token，与真实工作台一致。
 */

import { useState } from "react";
import {
  AtSign,
  ArrowUp,
  ArrowUpRight,
  Check,
  ChevronDown,
  FileText,
  MessageSquare,
  Plus,
  RotateCcw,
  Slash,
  X,
} from "lucide-react";
import { BrandMark } from "../components/Brand";
import "./intro-demo.css";

const PRESET_REQUEST = "请将付款期限从三十日调整为十五日。";

export default function WorkbenchDemo() {
  const [selected, setSelected] = useState(false);
  const [referenced, setReferenced] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [review, setReview] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [rejected, setRejected] = useState(false);
  const [request, setRequest] = useState("");
  const [panel, setPanel] = useState<"文档" | "会话">("文档");

  function selectClause() {
    setSelected(true);
  }
  function quote() {
    setSelected(true);
    setReferenced(true);
    setRequest(PRESET_REQUEST);
    setPanel("会话");
  }
  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!referenced || !request.trim()) return;
    setSubmitted(true);
    setReview(true);
    setRejected(false);
    setPanel("文档");
  }
  function accept() {
    setAccepted(true);
    setSelected(false);
  }
  function reject() {
    setReview(false);
    setRejected(true);
    setSelected(false);
  }
  function reset() {
    setSelected(false);
    setReferenced(false);
    setSubmitted(false);
    setReview(false);
    setAccepted(false);
    setRejected(false);
    setRequest("");
    setPanel("文档");
  }

  return (
    <section id="document-demo" className="lawver-demo-section" aria-labelledby="demo-title">
      <div className="section__heading">
        <p>亲手体验 · 虚构材料演示</p>
        <h2 id="demo-title">
          阅读、提问、审阅。
          <br />
          思考不必离开文档。
        </h2>
      </div>
      <p className="demo-intro">
        选择合同片段，提出要求，再决定是否接受修改。演示在本地运行，不上传内容、不调用模型。
      </p>
      <div className="demo-workbench">
        <aside className="demo-nav">
          <div className="intro-brand demo-nav__brand" aria-label="Lawver">
            <BrandMark className="h-7 w-7 shrink-0" />
            <span className="brand-wordmark">
              <span className="brand-wordmark-swash">L</span>awver
            </span>
          </div>
          <button className="demo-new" onClick={reset}>
            <Plus aria-hidden="true" />
            新建会话
          </button>
          <p>项目</p>
          <div className="demo-project is-active">
            <ChevronDown aria-hidden="true" />
            青禾 · 服务合同
          </div>
          <button onClick={() => setPanel("文档")}>
            <FileText aria-hidden="true" />
            技术服务合同
          </button>
          <button onClick={() => setPanel("会话")}>
            <MessageSquare aria-hidden="true" />
            合同付款条款审查
          </button>
          <small>所有名称与材料均为虚构</small>
        </aside>
        <nav className="demo-mobile-tabs" aria-label="演示面板切换">
          {(["文档", "会话"] as const).map((name) => (
            <button
              key={name}
              className={panel === name ? "is-active" : ""}
              onClick={() => setPanel(name)}
            >
              {name}
            </button>
          ))}
        </nav>
        <div className={"demo-document" + (panel !== "文档" ? " mobile-hidden" : "")}>
          <header>
            <span>技术服务合同</span>
            <small>{accepted ? "已保存 · 版本 2" : "版本 1 · 演示文档"}</small>
          </header>
          <article>
            <h3>技术服务合同</h3>
            <p className="demo-doc-meta">
              甲方：青禾科技有限公司（虚构）
              <br />
              乙方：远山技术工作室（虚构）
            </p>
            <h4>第一条　服务内容</h4>
            <p>乙方根据双方书面确认的需求提供技术服务，并于约定期限内提交成果，交由甲方验收。</p>
            <h4>第二条　费用与支付</h4>
            <p>2.1　服务费用及交付计划以双方确认的附件为准。</p>
            <button
              className={"demo-clause" + (selected ? " is-selected" : "")}
              onClick={selectClause}
              aria-label="选择付款期限条款"
            >
              2.2　甲方应在验收完成后
              {review && !accepted ? (
                <>
                  <del>三十日</del>
                  <ins>十五日</ins>
                </>
              ) : (
                <>{accepted ? "十五日" : "三十日"}</>
              )}
              内支付相应服务费用。
            </button>
            {selected && !review && (
              <div className="demo-selection-menu">
                <span>已选择付款条款</span>
                <button onClick={quote}>
                  询问修改
                  <ArrowUpRight aria-hidden="true" />
                </button>
              </div>
            )}
            <h4>第三条　保密义务</h4>
            <p>双方应对在合作过程中知悉的商业信息承担保密义务，未经对方书面同意，不向第三方披露。</p>
          </article>
          {review && !accepted && (
            <footer>
              <span>1 项修改建议</span>
              <button onClick={reject}>拒绝</button>
              <button className="demo-primary" onClick={accept}>
                接受修改
              </button>
            </footer>
          )}
        </div>
        <aside className={"demo-agent" + (panel !== "会话" ? " mobile-hidden" : "")}>
          <header>
            <span>Lawver</span>
            <small>与文档一起思考</small>
          </header>
          <div className="demo-conversation">
            <p className="demo-assistant">
              这份合同已准备就绪。试着选择付款条款，告诉我你希望如何调整。
            </p>
            {submitted && (
              <div className="demo-user">
                <small>@ 技术服务合同 · 付款条款</small>
                <p>{request}</p>
              </div>
            )}
            {review && (
              <div className="demo-assistant">
                <p>已将付款期限由三十日调整为十五日，其他约定保持不变。请审阅文档中的修改。</p>
                <small>这是预设的演示结果，并非法律意见。</small>
              </div>
            )}
            {accepted && (
              <p className="demo-success">
                <Check aria-hidden="true" />
                修改已接受，文档保存为新版本。原版本仍可追溯。
              </p>
            )}
            {rejected && <p>修改已拒绝，原文保持不变。</p>}
          </div>
          <form onSubmit={submit}>
            {referenced && (
              <div className="demo-reference">
                @ 付款条款 · v1
                <button type="button" aria-label="移除引用" onClick={() => setReferenced(false)}>
                  <X aria-hidden="true" />
                </button>
              </div>
            )}
            <textarea
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              aria-label="演示修改要求"
              placeholder="先选择文档中的付款条款…"
            />
            <div>
              <button type="button" onClick={quote}>
                <AtSign aria-hidden="true" />
                引用
              </button>
              <button type="button" onClick={() => setRequest(PRESET_REQUEST)}>
                <Slash aria-hidden="true" />
                修改条款
              </button>
              <button
                className="demo-primary"
                disabled={!referenced || !request.trim() || accepted}
                type="submit"
                aria-label="提交演示修改"
              >
                <ArrowUp aria-hidden="true" />
              </button>
            </div>
          </form>
          <button className="demo-reset" onClick={reset}>
            <RotateCcw aria-hidden="true" />
            重新体验
          </button>
        </aside>
      </div>
      <p className="demo-note">
        操作路径：选择付款条款 → 询问修改 → 发送要求 → 接受或拒绝。你也可以随时重新开始。
      </p>
    </section>
  );
}
