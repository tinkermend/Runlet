import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { apiFetch } from "../../../lib/http/client";
import type { AssetDetail } from "../../../lib/http/types";

function VersionBadge({ version }: { version: string }) {
  return (
    <span style={{
      display: "inline-block",
      padding: "2px 10px",
      borderRadius: 4,
      fontSize: 12,
      fontWeight: 600,
      background: "#1E293B",
      color: "#94A3B8",
      border: "1px solid #334155",
    }}>
      {version}
    </span>
  );
}

export function AssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [rawOpen, setRawOpen] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["asset", id],
    queryFn: () => apiFetch<AssetDetail>(`/api/console/assets/${id}`),
    enabled: !!id,
  });

  if (isLoading) return <div style={{ color: "#94A3B8" }}>加载中...</div>;
  if (error || !data) return <div style={{ color: "#EF4444" }}>加载失败，请刷新重试</div>;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <h1 style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700, margin: 0 }}>{data.page_name}</h1>
        <VersionBadge version={data.version} />
      </div>

      <div style={{ color: "#94A3B8", fontSize: 14, marginBottom: 24 }}>
        {data.system_name} · {data.check_type_label}
      </div>

      <div style={{ background: "#0F172A", border: "1px solid #334155", borderRadius: 8, padding: 16, marginBottom: 16 }}>
        <div style={{ color: "#94A3B8", fontSize: 13, marginBottom: 12, fontWeight: 600 }}>资产信息</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ color: "#64748B", fontSize: 13, width: 100 }}>状态</span>
            <span style={{ color: "#F8FAFC", fontSize: 13 }}>{data.status}</span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <span style={{ color: "#64748B", fontSize: 13, width: 100 }}>采集时间</span>
            <span style={{ color: "#F8FAFC", fontSize: 13 }}>
              {data.collected_at ? new Date(data.collected_at).toLocaleString("zh-CN") : "—"}
            </span>
          </div>
        </div>
      </div>

      <div style={{ background: "#0F172A", border: "1px solid #334155", borderRadius: 8, overflow: "hidden" }}>
        <button
          onClick={() => setRawOpen((v) => !v)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            width: "100%",
            padding: "12px 16px",
            background: "none",
            border: "none",
            cursor: "pointer",
            textAlign: "left",
          }}
        >
          {rawOpen ? <ChevronDown size={16} color="#94A3B8" /> : <ChevronRight size={16} color="#94A3B8" />}
          <span style={{ color: "#94A3B8", fontSize: 13, fontWeight: 600 }}>原始采集数据</span>
        </button>
        {rawOpen && (
          <div style={{ borderTop: "1px solid #334155", padding: 16 }}>
            {data.raw_facts ? (
              <pre style={{
                color: "#94A3B8",
                fontSize: 12,
                fontFamily: "monospace",
                margin: 0,
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
              }}>
                {JSON.stringify(data.raw_facts, null, 2)}
              </pre>
            ) : (
              <div style={{ color: "#64748B", fontSize: 13 }}>暂无原始数据</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
