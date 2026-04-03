import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Database, ChevronRight } from "lucide-react";
import { apiFetch } from "../../../lib/http/client";
import type { SystemAssetGroup } from "../../../lib/http/types";

function assetStatusClass(status: string) {
  switch (status) {
    case "active":  return "badge badge-success";
    case "stale":   return "badge badge-warning";
    case "error":   return "badge badge-danger";
    default:        return "badge badge-neutral";
  }
}

export function AssetBrowserPage() {
  const navigate = useNavigate();

  const { data, isLoading } = useQuery({
    queryKey: ["assets"],
    queryFn: () => apiFetch<SystemAssetGroup[]>("/api/console/assets/"),
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title" role="heading">采集资产</h1>
          <p className="page-subtitle">按系统和页面浏览已采集的检查资产</p>
        </div>
      </div>

      {isLoading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {[1,2].map(i => (
            <div key={i} className="card">
              <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
                <div className="skeleton" style={{ height: 16, width: "30%" }} />
              </div>
              {[1,2,3].map(j => (
                <div key={j} style={{ padding: "12px 24px", borderBottom: "1px solid var(--border-subtle)", display: "flex", gap: 12 }}>
                  <div className="skeleton" style={{ height: 13, flex: 1 }} />
                  <div className="skeleton" style={{ height: 13, width: 40 }} />
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <div className="empty-state-icon"><Database size={22} /></div>
            <div className="empty-state-title">暂无资产数据</div>
            <div className="empty-state-desc">接入系统并创建检查任务后，资产将在此显示</div>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {data.map((sysGroup) => (
            <div key={sysGroup.system_id} className="card" style={{ overflow: "hidden" }}>
              {/* System header */}
              <div style={{
                padding: "12px 16px",
                borderBottom: "1px solid var(--border)",
                background: "rgba(255,255,255,.02)",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}>
                <Database size={14} style={{ color: "var(--accent)" }} />
                <span style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>
                  {sysGroup.system_name}
                </span>
              </div>

              {sysGroup.pages.map((page, pi) => (
                <div key={page.page_name} style={{
                  borderBottom: pi < sysGroup.pages.length - 1 ? "1px solid var(--border-subtle)" : "none",
                }}>
                  {/* Page label */}
                  <div style={{
                    padding: "8px 16px",
                    fontSize: 12,
                    fontWeight: 600,
                    color: "var(--fg-dim)",
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    background: "rgba(255,255,255,.01)",
                  }}>
                    {page.page_name}
                  </div>

                  {/* Assets */}
                  {page.assets.map((asset, ai) => (
                    <button
                      key={asset.id}
                      onClick={() => navigate(`/assets/${asset.id}`)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        padding: "11px 24px",
                        background: "none",
                        border: "none",
                        borderBottom: ai < page.assets.length - 1 ? "1px solid var(--border-subtle)" : "none",
                        cursor: "pointer",
                        textAlign: "left",
                        width: "100%",
                        transition: "background var(--transition)",
                      }}
                      onMouseEnter={e => (e.currentTarget.style.background = "rgba(255,255,255,.02)")}
                      onMouseLeave={e => (e.currentTarget.style.background = "none")}
                    >
                      <span style={{ flex: 1, fontSize: 14, color: "var(--fg)", fontWeight: 500 }}>
                        {asset.check_type_label}
                      </span>
                      <span style={{
                        fontSize: 11, fontWeight: 600,
                        padding: "2px 7px", borderRadius: 4,
                        background: "var(--surface-2)", color: "var(--fg-dim)",
                        border: "1px solid var(--border)",
                      }}>
                        {asset.version}
                      </span>
                      <span className={assetStatusClass(asset.status)}>
                        {asset.status}
                      </span>
                      <ChevronRight size={14} style={{ color: "var(--fg-dim)", flexShrink: 0 }} />
                    </button>
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
