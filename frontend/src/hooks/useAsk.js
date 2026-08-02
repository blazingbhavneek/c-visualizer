import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { askStream, cancelAsk } from "../api.js";
import { useLang } from "../i18n.jsx";

const PROGRESS_EVENTS = new Set([
  "search",
  "candidates",
  "route",
  "subagents_spawned",
  "subagent_start",
  "read",
  "follow_link",
  "subagent_done",
  "compiling",
]);

export function activityLine(event, payload, lang = "ja") {
  const ja = lang !== "en";
  switch (event) {
    case "search":
      return `${ja ? "検索" : "Search"}: "${payload.query || ""}"`;
    case "candidates":
      return ja
        ? `候補 ${payload.items?.length || 0} 件`
        : `${payload.items?.length || 0} candidates`;
    case "route":
      return `${ja ? "経路" : "Route"}: ${payload.decision || "—"}`;
    case "subagents_spawned":
      return ja
        ? `サブエージェント ${payload.starts?.length || 0} 体を起動`
        : `Started ${payload.starts?.length || 0} subagents`;
    case "subagent_start":
      return `#${payload.agent} ${ja ? "開始" : "start"}: ${payload.node?.name || "—"}`;
    case "read":
      return `#${payload.agent} ${ja ? "読込" : "read"}: ${payload.name || "—"}`;
    case "follow_link":
      return `#${payload.agent} ${ja ? "追跡" : "follow"}: ${payload.name || "—"} (${payload.direction || "—"})`;
    case "subagent_done":
      return `#${payload.agent} ${ja ? "完了" : "done"}`;
    case "compiling":
      return ja ? "回答を作成中…" : "Compiling answer…";
    default:
      return null;
  }
}

function turnHistory(turns) {
  return turns
    .filter((turn) => turn.status === "complete")
    .flatMap((turn) => [
      { role: "user", content: turn.question },
      { role: "assistant", content: turn.answer },
    ])
    .slice(-6);
}

function updateTurn(setTurns, turnId, updater) {
  setTurns((current) =>
    current.map((turn) => (turn.id === turnId ? updater(turn) : turn)),
  );
}

export default function useAsk(selectedRuns) {
  const { lang } = useLang();
  const [turns, setTurns] = useState([]);
  const [activeRunId, setActiveRunId] = useState(null);
  const controllerRef = useRef(null);
  const activeTurnRef = useRef(null);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [],
  );

  const ask = useCallback(
    async (rawQuestion, mode = "deep") => {
      const question = rawQuestion.trim();
      if (!question || controllerRef.current) return false;

      const turnId = `${Date.now()}:${Math.random().toString(36).slice(2)}`;
      const controller = new AbortController();
      let terminal = false;
      controllerRef.current = controller;
      activeTurnRef.current = turnId;
      setActiveRunId(null);
      setTurns((current) => [
        ...current,
        {
          id: turnId,
          question,
          answer: "",
          cited: [],
          paths: [],
          resources: [],
          activity: [],
          stats: null,
          status: "streaming",
          error: null,
        },
      ]);

      try {
        await askStream(
          {
            question,
            runs: Object.fromEntries(selectedRuns),
            history: turnHistory(turns),
            mode,
            lang,
          },
          {
            signal: controller.signal,
            onEvent: (event, payload) => {
              if (event === "run") {
                setActiveRunId(payload.run_id || null);
                return;
              }
              if (PROGRESS_EVENTS.has(event)) {
                const line = activityLine(event, payload, lang);
                if (line) {
                  updateTurn(setTurns, turnId, (turn) => ({
                    ...turn,
                    activity: [...turn.activity, line].slice(-200),
                  }));
                }
                return;
              }
              if (event === "answer") {
                terminal = true;
                updateTurn(setTurns, turnId, (turn) => ({
                  ...turn,
                  answer: payload.text || "",
                  cited: payload.cited || [],
                  paths: payload.paths || [],
                  resources: payload.resources || [],
                  stats: payload.stats || null,
                  status: "complete",
                }));
                return;
              }
              if (event === "error") {
                terminal = true;
                updateTurn(setTurns, turnId, (turn) => ({
                  ...turn,
                  status: "error",
                  error: payload.message || "Unknown stream error.",
                }));
                return;
              }
              if (event === "cancelled") {
                terminal = true;
                updateTurn(setTurns, turnId, (turn) => ({ ...turn, status: "cancelled" }));
              }
              // Unknown event types are intentionally ignored for forwards compatibility.
            },
          },
        );
        if (!terminal) {
          updateTurn(setTurns, turnId, (turn) => ({
            ...turn,
            status: "error",
            error: "The answer stream closed before a terminal event.",
          }));
        }
      } catch (error) {
        if (error.name !== "AbortError") {
          updateTurn(setTurns, turnId, (turn) => ({
            ...turn,
            status: "error",
            error: error.message,
          }));
        }
      } finally {
        if (activeTurnRef.current === turnId) {
          controllerRef.current = null;
          activeTurnRef.current = null;
          setActiveRunId(null);
        }
      }
      return true;
    },
    [lang, selectedRuns, turns],
  );

  const stop = useCallback(async () => {
    const turnId = activeTurnRef.current;
    if (!turnId) return;
    updateTurn(setTurns, turnId, (turn) => ({ ...turn, status: "cancelled" }));
    if (activeRunId) cancelAsk(activeRunId).catch(() => {});
    controllerRef.current?.abort();
  }, [activeRunId]);

  const isStreaming = turns.some((turn) => turn.status === "streaming");
  const latestCompleted = useMemo(
    () => [...turns].reverse().find((turn) => turn.status === "complete") || null,
    [turns],
  );

  return { turns, ask, stop, isStreaming, activeRunId, latestCompleted };
}
