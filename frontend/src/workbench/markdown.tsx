import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

/*
 * 会话正文渲染的唯一入口，所有模型输出共用这一份管线，避免漂移。
 * 模型正文会夹带原生 HTML（联网引用的 <sup><a href>1</a></sup> 角标最常见），
 * remark 只认 markdown、裸 HTML 默认按字面转义——必须过 rehype-raw 才能成为节点。
 * 模型输出不可信，raw 之后紧跟 GitHub 级白名单消毒（默认 schema 已含 sup/sub/a），
 * script/事件属性/危险协议都在这一层拦掉。
 */
export function Markdown({ children }: { children?: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw, rehypeSanitize]}
    >
      {children || ""}
    </ReactMarkdown>
  );
}
