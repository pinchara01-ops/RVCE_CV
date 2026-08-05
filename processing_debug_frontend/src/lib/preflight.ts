import type { RuntimePreflight, RuntimePreflightDiagnostic } from "./api";

export type PreflightSummary = {
  tone: "ready" | "warning" | "error";
  headline: string;
  message: string;
  nextAction?: string;
};

const STAGE_LABELS: Record<string, string> = {
  profile_contract: "Embedding profile check",
  qdrant_cloud_connection: "Qdrant Cloud connection",
  local_qdrant_connection: "Local Qdrant connection",
  collection_schema: "Collection schema check",
  payload_indexes: "Library filter indexes",
};

export function preflightStageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage.replaceAll("_", " ");
}

export function preflightDiagnostics(preflight: RuntimePreflight): RuntimePreflightDiagnostic[] {
  if (preflight.diagnostics?.length) return preflight.diagnostics;
  if (preflight.error) {
    return [{
      stage: "qdrant_cloud_connection",
      status: "failed",
      message: preflight.error,
    }];
  }
  return [];
}

export function summarizeCloudPreflight(preflight: RuntimePreflight): PreflightSummary {
  const diagnostics = preflightDiagnostics(preflight);
  const failed = diagnostics.find((item) => item.status === "failed");
  const storeName = preflight.vector_store_target === "local" ? "Local Qdrant" : "Qdrant Cloud";
  const fallbackStage = preflight.vector_store_target === "local"
    ? "local_qdrant_connection"
    : "qdrant_cloud_connection";
  if (failed || !preflight.reachable || preflight.schema_valid === false) {
    const errorType = preflight.error_type ? `${preflight.error_type}: ` : "";
    return {
      tone: "error",
      headline: `${preflightStageLabel(failed?.stage ?? fallbackStage)} failed`,
      message: `${errorType}${failed?.message || preflight.error || `The ${storeName} preflight did not complete.`}`,
      nextAction: failed?.next_action || `Check the ${storeName} endpoint and retry.`,
    };
  }
  if (!preflight.collection_exists) {
    return {
      tone: "warning",
      headline: `${storeName} is ready`,
      message: "The compatible collection will be created on the first index run.",
      nextAction: "Start indexing when you are ready. No manual collection setup is needed.",
    };
  }
  return {
    tone: "ready",
    headline: `${storeName} is ready`,
    message: "The compatible collection matches the selected embedding profile.",
  };
}
