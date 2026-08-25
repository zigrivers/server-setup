// local-stall-alert — tell the operator when a turn dies instead of letting it end in silence.
//
// Why this exists. When a local mlx endpoint wedges or 502s, OpenCode retries three times, logs
// `AI_RetryError: Failed after 3 attempts`, and then the turn simply ends. Nothing appears in the
// UI. Measured on this stack: on 2026-08-25 between 00:00 and 04:00 every single local turn failed
// — 40 of 40 — and the only symptom the operator saw was the session going quiet, so they typed
// "continue". Two upstream bugs make this worse and are not fixable from here:
//   - SSE/chunk timeouts are not classified as retryable, so the turn dies with no retry
//     (ml-explore is not involved; this is anomalyco/opencode#20466)
//   - a successful response with zero content reads as "task complete" (opencode#31430)
// This plugin does not fix either. It makes them visible, which is the part that was missing.
//
// Wire it up in opencode.json:
//   { "plugin": ["/Users/kenallred/Developer/server-setup/configs/opencode/plugins/local-stall-alert.mjs"] }

const NOTIFY_COOLDOWN_MS = 60_000; // one alert a minute — an outage fires this on every retry

let lastNotifiedAt = 0;

/** Pull a short human-readable reason out of whatever shape the error payload arrives in. */
function describe(properties) {
  const error = properties?.error ?? properties;
  if (!error) return "unknown error";
  const raw =
    error.data?.message ??
    error.message ??
    error.name ??
    (typeof error === "string" ? error : JSON.stringify(error));
  return String(raw).replace(/\s+/g, " ").slice(0, 160);
}

export const LocalStallAlert = async ({ $ }) => {
  return {
    event: async ({ event }) => {
      if (event?.type !== "session.error") return;

      const now = Date.now();
      if (now - lastNotifiedAt < NOTIFY_COOLDOWN_MS) return;
      lastNotifiedAt = now;

      const reason = describe(event.properties);
      // `launchpad notify` is the house notifier and is already on PATH for interactive shells.
      // Never let a failed notification take down the session that is already having a bad time.
      try {
        await $`launchpad notify ${`OpenCode turn failed — ${reason}`}`.quiet();
      } catch {
        try {
          await $`osascript -e ${`display notification ${JSON.stringify(reason)} with title "OpenCode turn failed"`}`.quiet();
        } catch {
          // Both notifiers unavailable (headless run, no launchpad). Nothing further to try;
          // the error is still in OpenCode's own log.
        }
      }
    },
  };
};

export default LocalStallAlert;
