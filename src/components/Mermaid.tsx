import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'loose',
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
        if (isMounted) {
          setSvg(renderedSvg);
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
