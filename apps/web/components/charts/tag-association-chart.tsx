"use client";

import { GraphChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import type { TagAssociationEdge } from "../../types/api";

echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);

export function TagAssociationChart({ edges }: { edges: TagAssociationEdge[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graph = useMemo(() => {
    const nodes = new Map<string, { name: string; value: number; translation: string | null }>();
    for (const edge of edges) {
      nodes.set(edge.left.tag_name, {
        name: edge.left.tag_name,
        value: edge.left.sampled_work_count,
        translation: edge.left.tag_translation,
      });
      nodes.set(edge.right.tag_name, {
        name: edge.right.tag_name,
        value: edge.right.sampled_work_count,
        translation: edge.right.tag_translation,
      });
    }
    return {
      nodes: [...nodes.values()],
      links: edges.map((edge) => ({
        source: edge.left.tag_name,
        target: edge.right.tag_name,
        value: edge.cooccurrence_work_count,
        lineStyle: {
          width: Math.max(1, Math.min(8, Math.sqrt(edge.cooccurrence_work_count) * 2)),
        },
      })),
    };
  }, [edges]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || graph.nodes.length === 0) return;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    chart.setOption({
      animation: false,
      tooltip: { trigger: "item" },
      series: [{
        type: "graph",
        layout: "force",
        roam: true,
        draggable: false,
        force: { repulsion: 180, edgeLength: [70, 150], gravity: 0.08 },
        label: { show: true, color: "#f7f3f6", position: "right" },
        itemStyle: { color: "#ffb5d2", borderColor: "#100d12", borderWidth: 2 },
        lineStyle: { color: "#8de2cb", opacity: 0.62, curveness: 0.08 },
        symbolSize: (value: number) => Math.max(16, Math.min(48, 12 + Math.sqrt(value) * 7)),
        data: graph.nodes,
        links: graph.links,
      }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [graph]);

  if (edges.length === 0) {
    return <p className="chart-empty">当前样本和筛选条件下没有标签关系。</p>;
  }
  return (
    <div
      className="tag-association-chart"
      ref={containerRef}
      role="img"
      aria-label={`标签关系图，共 ${graph.nodes.length} 个标签、${edges.length} 条描述性关系`}
    />
  );
}
