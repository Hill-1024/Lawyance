/*
 * 模块描述：安全 Mermaid 渲染组件，负责图表渲染、SVG 清洗和错误降级展示。
 */

import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import DOMPurify from 'dompurify';

mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'strict',
  flowchart: {
    htmlLabels: false,
  },
  sequence: {
    useMaxWidth: true,
  },
});

interface MermaidProps {
  chart: string;
}

export const Mermaid: React.FC<MermaidProps> = ({ chart }) => {
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string>('');
  const id = useRef(`mermaid-${Math.random().toString(36).substring(2, 11)}`);

  useEffect(() => {
    let isMounted = true;

    const renderChart = async () => {
      try {
        const { svg: renderedSvg } = await mermaid.render(id.current, chart);
        const sanitizedSvg = DOMPurify.sanitize(renderedSvg, {
          USE_PROFILES: { svg: true, svgFilters: true },
          FORBID_TAGS: ['foreignObject', 'script'],
          SAFE_FOR_XML: true,
        });
        if (isMounted) {
          setSvg(sanitizedSvg);
          setError('');
        }
      } catch (e: any) {
        if (isMounted) {
          console.error('Mermaid render error:', e);
          setError(e.message || 'Failed to render diagram');
        }
      }
    };

    renderChart();

    return () => {
      isMounted = false;
    };
  }, [chart]);

  if (error) {
    return (
      <div className="overflow-auto rounded-[var(--radius-md)] border border-[rgba(176,70,62,0.3)] bg-[rgba(176,70,62,0.1)] p-4 font-mono text-sm text-[var(--color-danger-500)]">
        <p className="font-bold mb-2">Mermaid Error:</p>
        <pre>{error}</pre>
        <p className="mt-2 font-bold">Source:</p>
        <pre>{chart}</pre>
      </div>
    );
  }

  return svg ? (
    <div
      className="mermaid-wrapper my-4 flex justify-center overflow-auto"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  ) : (
    <div className="flex items-center justify-center p-4 text-sm text-[var(--fg-3)]">
      Rendering diagram...
    </div>
  );
};
