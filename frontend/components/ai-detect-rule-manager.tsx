"use client";

import { api, showApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  AIDetectionRule,
  AIDetectionRuleScope,
  AIDetectionRuleSeverity,
  CompiledAIDetectionRule,
} from "@/lib/types";
import clsx from "clsx";
import {
  AlertCircle,
  BrainCircuit,
  Loader2,
  PencilLine,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  WandSparkles,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

function canMutateRule(rule: AIDetectionRule, userId: string | undefined, isAdmin: boolean) {
  if (rule.scope === "global") return isAdmin;
  return rule.owner_id === userId;
}

function formatRuleScope(scope: AIDetectionRuleScope) {
  return scope === "global" ? "Global" : "Cá nhân";
}

export function AIDetectionRuleManager() {
  const { token, user } = useAuth();
  const [rules, setRules] = useState<AIDetectionRule[]>([]);
  const [isLoadingRules, setIsLoadingRules] = useState(false);
  const [isCompiling, setIsCompiling] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [compiledRule, setCompiledRule] = useState<CompiledAIDetectionRule | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<AIDetectionRuleSeverity>("medium");
  const [weight, setWeight] = useState("0.2");
  const [enabled, setEnabled] = useState(true);
  const [scope, setScope] = useState<AIDetectionRuleScope>("user");
  const isMountedRef = useRef(true);

  const isAdmin = user?.role === "admin";

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadRules = useCallback(async () => {
    if (!token) return;
    setIsLoadingRules(true);
    try {
      const nextRules = await api.listAIDetectionRules(token);
      if (!isMountedRef.current) return;
      setRules(nextRules);
    } catch (error) {
      if (!isMountedRef.current) return;
      showApiError(error);
    } finally {
      if (!isMountedRef.current) return;
      setIsLoadingRules(false);
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    void loadRules();
  }, [loadRules, token]);

  const effectiveCompiledRule = useMemo<CompiledAIDetectionRule | null>(() => {
    if (!compiledRule) return null;
    return {
      ...compiledRule,
      name: name.trim() || compiledRule.name,
      description: description.trim() || compiledRule.description || null,
      severity,
      weight: Number(weight) || compiledRule.weight,
    };
  }, [compiledRule, description, name, severity, weight]);

  const resetDraft = () => {
    setEditingRuleId(null);
    setSourceText("");
    setCompiledRule(null);
    setWarnings([]);
    setName("");
    setDescription("");
    setSeverity("medium");
    setWeight("0.2");
    setEnabled(true);
    setScope("user");
  };

  const applyDraftFromRule = (rule: AIDetectionRule) => {
    setEditingRuleId(rule.id);
    setSourceText(rule.source_text);
    setCompiledRule(rule.rule_json);
    setWarnings([]);
    setName(rule.name);
    setDescription(rule.description || "");
    setSeverity(rule.severity);
    setWeight(String(rule.weight));
    setEnabled(rule.enabled);
    setScope(rule.scope);
  };

  const handleCompile = async () => {
    if (!token || !sourceText.trim()) return;
    setIsCompiling(true);
    try {
      const result = await api.compileAIDetectionRule(token, sourceText.trim());
      setCompiledRule(result.compiled_rule);
      setWarnings(result.warnings);
      setName(result.compiled_rule.name);
      setDescription(result.compiled_rule.description || "");
      setSeverity(result.compiled_rule.severity);
      setWeight(String(result.compiled_rule.weight));
      toast.success("Đã compile rule tự nhiên.");
    } catch (error) {
      showApiError(error);
    } finally {
      setIsCompiling(false);
    }
  };

  const handleSave = async () => {
    if (!token || !sourceText.trim()) return;
    setIsSaving(true);
    try {
      const payload = {
        source_text: sourceText.trim(),
        compiled_rule: effectiveCompiledRule || undefined,
        scope,
        enabled,
      };
      if (editingRuleId) {
        await api.updateAIDetectionRule(token, editingRuleId, {
          source_text: sourceText.trim(),
          compiled_rule: effectiveCompiledRule || undefined,
          enabled,
          scope,
          name: name.trim() || undefined,
          description: description.trim() || undefined,
          severity,
          weight: Number(weight) || undefined,
        });
        toast.success("Đã cập nhật custom rule.");
      } else {
        await api.createAIDetectionRule(token, payload);
        toast.success("Đã lưu custom rule.");
      }
      await loadRules();
      resetDraft();
    } catch (error) {
      showApiError(error);
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggle = async (rule: AIDetectionRule) => {
    if (!token) return;
    try {
      await api.updateAIDetectionRule(token, rule.id, { enabled: !rule.enabled });
      await loadRules();
    } catch (error) {
      showApiError(error);
    }
  };

  const handleDelete = async (ruleId: string) => {
    if (!token) return;
    try {
      await api.deleteAIDetectionRule(token, ruleId);
      toast.success("Đã xóa custom rule.");
      if (editingRuleId === ruleId) resetDraft();
      await loadRules();
    } catch (error) {
      showApiError(error);
    }
  };

  return (
    <section className="rounded-2xl border border-border bg-bg-secondary/30 p-4 dark:border-white/8 dark:bg-white/[0.02]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <BrainCircuit size={16} className="text-accent dark:text-dark-accent" />
            <h3 className="text-sm font-semibold text-text-primary dark:text-dark-text-primary">
              Structured AI detection rules
            </h3>
          </div>
          <p className="mt-1 text-xs leading-5 text-text-secondary dark:text-dark-text-secondary">
            Viết rule bằng ngôn ngữ tự nhiên, để AIRA compile thành JSON có cấu trúc rồi áp dụng như một lớp evidence bổ sung.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={resetDraft}
            className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-xs text-text-secondary transition-colors hover:bg-bg-secondary hover:text-text-primary dark:border-white/10 dark:text-dark-text-secondary dark:hover:bg-white/[0.05] dark:hover:text-dark-text-primary"
          >
            <Plus size={13} />
            Rule mới
          </button>
          <button
            type="button"
            onClick={() => void loadRules()}
            className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-xs text-text-secondary transition-colors hover:bg-bg-secondary hover:text-text-primary dark:border-white/10 dark:text-dark-text-secondary dark:hover:bg-white/[0.05] dark:hover:text-dark-text-primary"
          >
            <RefreshCw size={13} />
            Tải lại
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-3">
          <label className="block">
            <span className="text-xs font-medium text-text-primary dark:text-dark-text-primary">
              Rule bằng ngôn ngữ tự nhiên
            </span>
            <textarea
              value={sourceText}
              onChange={(event) => setSourceText(event.target.value)}
              rows={6}
              placeholder="Ví dụ: Đánh dấu các đoạn văn quá chung chung, dùng nhiều cụm như &quot;it is important to note that&quot;, thiếu ví dụ cụ thể và lặp cấu trúc câu."
              className="mt-2 min-h-[160px] w-full resize-y rounded-2xl border border-border bg-surface px-3.5 py-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-tertiary focus:border-accent focus:ring-2 focus:ring-accent/20 dark:border-white/10 dark:bg-[#111313] dark:text-dark-text-primary dark:placeholder:text-dark-text-tertiary dark:focus:border-dark-accent dark:focus:ring-dark-accent/20"
            />
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs font-medium text-text-primary dark:text-dark-text-primary">Tên rule</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-2 w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 dark:border-white/10 dark:bg-[#111313] dark:text-dark-text-primary dark:focus:border-dark-accent dark:focus:ring-dark-accent/20"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-text-primary dark:text-dark-text-primary">Severity</span>
              <select
                value={severity}
                onChange={(event) => setSeverity(event.target.value as AIDetectionRuleSeverity)}
                className="mt-2 w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 dark:border-white/10 dark:bg-[#111313] dark:text-dark-text-primary dark:focus:border-dark-accent dark:focus:ring-dark-accent/20"
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </label>
            <label className="block sm:col-span-2">
              <span className="text-xs font-medium text-text-primary dark:text-dark-text-primary">Mô tả</span>
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="mt-2 w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 dark:border-white/10 dark:bg-[#111313] dark:text-dark-text-primary dark:focus:border-dark-accent dark:focus:ring-dark-accent/20"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-text-primary dark:text-dark-text-primary">Weight</span>
              <input
                value={weight}
                onChange={(event) => setWeight(event.target.value)}
                inputMode="decimal"
                className="mt-2 w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 dark:border-white/10 dark:bg-[#111313] dark:text-dark-text-primary dark:focus:border-dark-accent dark:focus:ring-dark-accent/20"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-text-primary dark:text-dark-text-primary">Scope</span>
              <select
                value={scope}
                onChange={(event) => setScope(event.target.value as AIDetectionRuleScope)}
                disabled={!isAdmin}
                className="mt-2 w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60 dark:border-white/10 dark:bg-[#111313] dark:text-dark-text-primary dark:focus:border-dark-accent dark:focus:ring-dark-accent/20"
              >
                <option value="user">user</option>
                <option value="global">global</option>
              </select>
            </label>
          </div>

          <label className="flex items-center gap-2 text-xs text-text-secondary dark:text-dark-text-secondary">
            <input
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              type="checkbox"
              className="h-4 w-4 rounded border-border text-accent focus:ring-accent/20 dark:border-white/10"
            />
            Rule đang bật
          </label>

          {warnings.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/40 dark:bg-amber-900/10 dark:text-amber-200">
              {warnings.map((warning) => (
                <div key={warning} className="flex items-start gap-2">
                  <AlertCircle size={12} className="mt-0.5 shrink-0" />
                  <span>{warning}</span>
                </div>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void handleCompile()}
              disabled={!token || !sourceText.trim() || isCompiling}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-text-primary transition-colors hover:bg-bg-secondary disabled:opacity-50 dark:border-white/10 dark:text-dark-text-primary dark:hover:bg-white/[0.05]"
            >
              {isCompiling ? <Loader2 size={14} className="animate-spin" /> : <WandSparkles size={14} />}
              Compile rule
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={!token || !sourceText.trim() || isSaving}
              className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-60 dark:bg-dark-accent dark:text-dark-bg-primary dark:hover:bg-dark-accent-hover"
            >
              {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              {editingRuleId ? "Cập nhật rule" : "Lưu rule"}
            </button>
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-2xl border border-border bg-surface p-3 dark:border-white/10 dark:bg-[#111313]">
            <div className="text-xs font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
              Preview JSON
            </div>
            <pre className="mt-2 max-h-[360px] overflow-auto whitespace-pre-wrap rounded-xl bg-bg-secondary/60 p-3 text-[11px] leading-5 text-text-secondary dark:bg-white/[0.04] dark:text-dark-text-secondary">
              {effectiveCompiledRule
                ? JSON.stringify(effectiveCompiledRule, null, 2)
                : "Compile rule để xem structured JSON preview."}
            </pre>
          </div>

          <div className="rounded-2xl border border-border bg-surface p-3 dark:border-white/10 dark:bg-[#111313]">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold uppercase tracking-wide text-text-tertiary dark:text-dark-text-tertiary">
                Rules đã lưu
              </div>
              {isLoadingRules && <Loader2 size={13} className="animate-spin text-text-tertiary dark:text-dark-text-tertiary" />}
            </div>
            <div className="mt-3 space-y-2">
              {rules.length === 0 && !isLoadingRules && (
                <p className="text-xs text-text-secondary dark:text-dark-text-secondary">
                  Chưa có structured custom rule nào.
                </p>
              )}
              {rules.map((rule) => {
                const canMutate = canMutateRule(rule, user?.id, Boolean(isAdmin));
                return (
                  <div
                    key={rule.id}
                    className={clsx(
                      "rounded-xl border p-3 transition-colors",
                      editingRuleId === rule.id
                        ? "border-accent/40 bg-accent/5 dark:border-dark-accent/40 dark:bg-dark-accent/10"
                        : "border-border dark:border-white/10",
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-text-primary dark:text-dark-text-primary">
                            {rule.name}
                          </span>
                          <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-[10px] uppercase text-text-secondary dark:bg-white/[0.06] dark:text-dark-text-secondary">
                            {rule.rule_type}
                          </span>
                          <span className="rounded-full bg-bg-secondary px-2 py-0.5 text-[10px] uppercase text-text-secondary dark:bg-white/[0.06] dark:text-dark-text-secondary">
                            {formatRuleScope(rule.scope)}
                          </span>
                          {!rule.enabled && (
                            <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] uppercase text-red-700 dark:bg-red-900/20 dark:text-red-400">
                              disabled
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs leading-5 text-text-secondary dark:text-dark-text-secondary">
                          {rule.description || "Không có mô tả."}
                        </p>
                        <div className="mt-1 text-[11px] text-text-tertiary dark:text-dark-text-tertiary">
                          Severity: {rule.severity} | Weight: {rule.weight}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          onClick={() => applyDraftFromRule(rule)}
                          className="rounded-lg p-1.5 text-text-secondary transition-colors hover:bg-bg-secondary hover:text-text-primary dark:text-dark-text-secondary dark:hover:bg-white/[0.05] dark:hover:text-dark-text-primary"
                          title="Nạp vào editor"
                        >
                          <PencilLine size={14} />
                        </button>
                        {canMutate && (
                          <>
                            <button
                              type="button"
                              onClick={() => void handleToggle(rule)}
                              className="rounded-lg p-1.5 text-text-secondary transition-colors hover:bg-bg-secondary hover:text-text-primary dark:text-dark-text-secondary dark:hover:bg-white/[0.05] dark:hover:text-dark-text-primary"
                              title={rule.enabled ? "Tắt rule" : "Bật rule"}
                            >
                              <BrainCircuit size={14} />
                            </button>
                            <button
                              type="button"
                              onClick={() => void handleDelete(rule.id)}
                              className="rounded-lg p-1.5 text-text-secondary transition-colors hover:bg-red-50 hover:text-red-700 dark:text-dark-text-secondary dark:hover:bg-red-900/20 dark:hover:text-red-400"
                              title="Xóa rule"
                            >
                              <Trash2 size={14} />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
