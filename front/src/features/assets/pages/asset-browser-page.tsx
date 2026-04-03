import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../../../lib/http/client";
import type { SystemAssetGroup } from "../../../lib/http/types";

const STATUS_COLORS: Record<string, string> = {
  active: "#22C55E",
  draft: "#64748B",
  stale: "#F59E0B",
  error: "#EF4444",
};

function VersionBadge({ version }: { version: string }) {
  return (
    <span style={{
      display: "inline-block",
      padding: "1px 8px",
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 600,
      background: "#1E293B",
      color: "#94A3B8",
      border: "1px solid #334155",
    }}>
      {version}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? "#64748B";
  return (
    <span style={{
      display: "inline-block",
      padding: "1px 8px",
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 600,
      background: color + "22",
      color,
      border: `1px solid ${color}44`,
    }}>
      {status}
    </span>
  );
}

export function AssetBrowserPage() {
  const navigate = useNavigate();

  const { data, isLoading, error } = useQuery({
    queryKey: ["assets"],
    queryFn: () => apiFetch<SystemAssetGroup[]>("/api/console/assets/"),
  });

  if (isLoading) return <div style={{ color: "#94A3B8" }}>加载中...</div>;
  if (error || !data) return <div style={{ color: "#EF4444" }}>加载失败，请刷新重试</div>;

  return (
    <div>
      <h1 role="heading" style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700, marginBottom: 24 }}>采集资产</h1>

      {data.length === 0 ? (
        <div style={{ color: "#64748B", fontSize: 14 }}>暂无资产数据</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {data.map((sysGroup) => (
            <div key={sysGroup.system_id} style={{ background: "#0F172A", border: "1px solid #334155", borderRadius: 8, overflow: "hidden" }}>
              <div style={{ padding: "12px 16px", borderBottom: "1px solid #334155", background: "#1E293B" }}>
                <span style={{ color: "#F8FAFC", fontSize: 15, fontWeight: 600 }}>{sysGroup.system_name}</span>
              </div>

              {sysGroup.pages.map((page) => (
                <div key={page.page_name} style={{ borderBottom: "1px solid #1E293B" }}>
                  <div style={{ padding: "10px 16px", background: "#0F172A44" }}>
                    <span style={{ color: "#94A3B8", fontSize: 13, fontWeight: 500 }}>{page.page_name}</span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    {page.assets.map((asset, i) => (
                      <button
                        key={asset.id}
                        onClick={() => navigate(`/assets/${asset.id}`)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 12,
                          padding: "10px 24px",
                          background: "none",
                          border: "none",
                          borderBottom: i < page.assets.length - 1 ? "1px solid #1E293B" : "none",
                          cursor: "pointer",
                          textAlign: "left",
                          width: "100%",
                        }}
                      >
                        <span style={{ color: "#F8FAFC", fontSize: 14, flex: 1 }}>{asset.check_type_label}</span>
                        <VersionBadge version={asset.version} />
                        <StatusBadge status={asset.status} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
