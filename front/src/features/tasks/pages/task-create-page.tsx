import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../../../lib/http/client";
import type { WizardOptions } from "../../../lib/http/types";

const CHECK_TYPE_LABELS: Record<string, string> = {
  menu_completeness: "菜单完整性",
  element_existence: "页面元素存在性",
};

const SCHEDULE_OPTIONS = [
  { value: "hourly", label: "每小时" },
  { value: "daily", label: "每天" },
  { value: "manual", label: "手动触发" },
];

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 32 }}>
      {Array.from({ length: total }, (_, i) => {
        const step = i + 1;
        const active = step === current;
        const done = step < current;
        return (
          <div key={step} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 13,
              fontWeight: 700,
              background: active ? "#22C55E" : done ? "#22C55E44" : "#1E293B",
              color: active ? "#020617" : done ? "#22C55E" : "#64748B",
              border: `2px solid ${active || done ? "#22C55E" : "#334155"}`,
            }}>
              {step}
            </div>
            {step < total && <div style={{ width: 32, height: 2, background: done ? "#22C55E44" : "#334155" }} />}
          </div>
        );
      })}
      <span style={{ color: "#94A3B8", fontSize: 13, marginLeft: 8 }}>步骤 {current}/{total}</span>
    </div>
  );
}

export function TaskCreatePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [selectedSystem, setSelectedSystem] = useState<number | null>(null);
  const [selectedCheckTypes, setSelectedCheckTypes] = useState<string[]>([]);
  const [schedulePreset, setSchedulePreset] = useState("daily");
  const [timeout, setTimeout_] = useState(30);
  const [taskName, setTaskName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const { data: wizardOptions, isLoading } = useQuery({
    queryKey: ["wizard-options"],
    queryFn: () => apiFetch<WizardOptions>("/api/console/tasks/wizard-options"),
  });

  function toggleCheckType(ct: string) {
    setSelectedCheckTypes((prev) =>
      prev.includes(ct) ? prev.filter((x) => x !== ct) : [...prev, ct]
    );
  }

  async function handleSubmit() {
    if (!taskName.trim()) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await apiFetch("/api/console/tasks/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: taskName,
          system_id: selectedSystem,
          check_types: selectedCheckTypes,
          schedule_preset: schedulePreset,
          timeout_seconds: timeout,
        }),
      });
      navigate("/tasks");
    } catch (e) {
      setSubmitError("创建失败，请重试");
    } finally {
      setSubmitting(false);
    }
  }

  const systemName = wizardOptions?.systems.find((s) => s.id === selectedSystem)?.name ?? "—";
  const scheduleLabel = SCHEDULE_OPTIONS.find((o) => o.value === schedulePreset)?.label ?? schedulePreset;

  return (
    <div style={{ maxWidth: 600 }}>
      <h1 style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700, marginBottom: 24 }}>新建检查任务</h1>
      <StepIndicator current={step} total={3} />

      {step === 1 && (
        <div>
          <h2 style={{ color: "#F8FAFC", fontSize: 18, fontWeight: 600, marginBottom: 20 }}>选择检查目标</h2>
          {isLoading ? (
            <div style={{ color: "#94A3B8" }}>加载中...</div>
          ) : (
            <>
              <div style={{ marginBottom: 24 }}>
                <div style={{ color: "#94A3B8", fontSize: 13, marginBottom: 10 }}>选择系统</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {wizardOptions?.systems.map((sys) => (
                    <label key={sys.id} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                      <input
                        type="radio"
                        name="system"
                        value={sys.id}
                        checked={selectedSystem === sys.id}
                        onChange={() => setSelectedSystem(sys.id)}
                        style={{ accentColor: "#22C55E" }}
                      />
                      <span style={{ color: "#F8FAFC", fontSize: 14 }}>{sys.name}</span>
                      <span style={{ color: "#64748B", fontSize: 12 }}>{sys.base_url}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div style={{ marginBottom: 24 }}>
                <div style={{ color: "#94A3B8", fontSize: 13, marginBottom: 10 }}>检查类型</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {wizardOptions?.check_types.map((ct) => (
                    <label key={ct} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={selectedCheckTypes.includes(ct)}
                        onChange={() => toggleCheckType(ct)}
                        style={{ accentColor: "#22C55E" }}
                      />
                      <span style={{ color: "#F8FAFC", fontSize: 14 }}>
                        {CHECK_TYPE_LABELS[ct] ?? ct}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {step === 2 && (
        <div>
          <h2 style={{ color: "#F8FAFC", fontSize: 18, fontWeight: 600, marginBottom: 20 }}>配置参数</h2>

          <div style={{ marginBottom: 24 }}>
            <div style={{ color: "#94A3B8", fontSize: 13, marginBottom: 10 }}>调度频率</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {SCHEDULE_OPTIONS.map((opt) => (
                <label key={opt.value} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="schedule"
                    value={opt.value}
                    checked={schedulePreset === opt.value}
                    onChange={() => setSchedulePreset(opt.value)}
                    style={{ accentColor: "#22C55E" }}
                  />
                  <span style={{ color: "#F8FAFC", fontSize: 14 }}>{opt.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div style={{ marginBottom: 24 }}>
            <label style={{ color: "#94A3B8", fontSize: 13, display: "block", marginBottom: 8 }}>
              超时时间（秒）
            </label>
            <input
              type="number"
              value={timeout}
              min={5}
              max={300}
              onChange={(e) => setTimeout_(Number(e.target.value))}
              style={{
                width: 120,
                padding: "8px 12px",
                background: "#1E293B",
                border: "1px solid #334155",
                borderRadius: 6,
                color: "#F8FAFC",
                fontSize: 14,
              }}
            />
          </div>
        </div>
      )}

      {step === 3 && (
        <div>
          <h2 style={{ color: "#F8FAFC", fontSize: 18, fontWeight: 600, marginBottom: 20 }}>确认并创建</h2>

          <div style={{ marginBottom: 20 }}>
            <label style={{ color: "#94A3B8", fontSize: 13, display: "block", marginBottom: 8 }}>
              任务名称 <span style={{ color: "#EF4444" }}>*</span>
            </label>
            <input
              type="text"
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              placeholder="请输入任务名称"
              style={{
                width: "100%",
                padding: "8px 12px",
                background: "#1E293B",
                border: "1px solid #334155",
                borderRadius: 6,
                color: "#F8FAFC",
                fontSize: 14,
                boxSizing: "border-box",
              }}
            />
          </div>

          <div style={{ background: "#0F172A", border: "1px solid #334155", borderRadius: 8, padding: 16, marginBottom: 20 }}>
            <div style={{ color: "#94A3B8", fontSize: 13, marginBottom: 12 }}>配置摘要</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", gap: 8 }}>
                <span style={{ color: "#64748B", fontSize: 13, width: 80 }}>系统</span>
                <span style={{ color: "#F8FAFC", fontSize: 13 }}>{systemName}</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <span style={{ color: "#64748B", fontSize: 13, width: 80 }}>检查类型</span>
                <span style={{ color: "#F8FAFC", fontSize: 13 }}>
                  {selectedCheckTypes.map((ct) => CHECK_TYPE_LABELS[ct] ?? ct).join("、") || "—"}
                </span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <span style={{ color: "#64748B", fontSize: 13, width: 80 }}>调度频率</span>
                <span style={{ color: "#F8FAFC", fontSize: 13 }}>{scheduleLabel}</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <span style={{ color: "#64748B", fontSize: 13, width: 80 }}>超时时间</span>
                <span style={{ color: "#F8FAFC", fontSize: 13 }}>{timeout} 秒</span>
              </div>
            </div>
          </div>

          {submitError && <div style={{ color: "#EF4444", fontSize: 13, marginBottom: 12 }}>{submitError}</div>}
        </div>
      )}

      <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
        {step > 1 && (
          <button
            onClick={() => setStep((s) => s - 1)}
            style={{
              padding: "8px 20px",
              background: "transparent",
              color: "#94A3B8",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            上一步
          </button>
        )}
        {step < 3 && (
          <button
            onClick={() => setStep((s) => s + 1)}
            style={{
              padding: "8px 20px",
              background: "#22C55E",
              color: "#020617",
              border: "none",
              borderRadius: 6,
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            下一步
          </button>
        )}
        {step === 3 && (
          <button
            onClick={handleSubmit}
            disabled={!taskName.trim() || submitting}
            style={{
              padding: "8px 20px",
              background: taskName.trim() ? "#22C55E" : "#334155",
              color: taskName.trim() ? "#020617" : "#64748B",
              border: "none",
              borderRadius: 6,
              fontSize: 14,
              fontWeight: 600,
              cursor: taskName.trim() ? "pointer" : "not-allowed",
            }}
          >
            {submitting ? "创建中..." : "创建任务"}
          </button>
        )}
      </div>
    </div>
  );
}
