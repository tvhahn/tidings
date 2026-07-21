import { useEffect, useState } from "react";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import {
  AUTH_STATE_CHANGED_EVENT,
  fetchHealth,
  logout,
  setAppPassword,
  signOutAllDevices,
} from "@/lib/api";

function useAuthRequired() {
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);
  const refresh = async () => {
    try {
      const health = await fetchHealth();
      setAuthRequired(health.auth_required);
    } catch {
      setAuthRequired(null);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);
  return { authRequired, refresh };
}

type Feedback = { kind: "ok" | "err"; text: string } | null;

function FeedbackLine({ feedback }: { feedback: Feedback }) {
  if (!feedback) return null;
  return (
    <p
      className={
        feedback.kind === "ok"
          ? "text-sm text-status-ok-accent"
          : "text-sm text-status-danger-accent"
      }
    >
      {feedback.text}
    </p>
  );
}

export function AccessPasswordSection() {
  const { authRequired, refresh } = useAuthRequired();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);

  if (authRequired === null) return null;

  const settingFirst = !authRequired;
  const submitLabel = submitting ? "Saving…" : settingFirst ? "Set password" : "Change password";

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFeedback(null);
    if (newPassword.length < 8) {
      setFeedback({ kind: "err", text: "Password must be at least 8 characters" });
      return;
    }
    if (newPassword !== confirmPassword) {
      setFeedback({ kind: "err", text: "Passwords don't match" });
      return;
    }
    setSubmitting(true);
    try {
      await setAppPassword({
        password: newPassword,
        ...(authRequired ? { current_password: currentPassword } : {}),
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setFeedback({ kind: "ok", text: "Password updated" });
      await refresh();
      window.dispatchEvent(new CustomEvent(AUTH_STATE_CHANGED_EVENT));
    } catch (err) {
      setFeedback({
        kind: "err",
        text: err instanceof Error ? err.message : "Failed to update password",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="space-y-4" id="access">
      <SettingsSectionHeader
        title={settingFirst ? "Set a password" : "Password"}
        infoHint={{
          label: "About Access",
          content: settingFirst
            ? "Set a password to gate the dashboard. Anyone reaching this URL will see a login screen until they enter it. Agents and scripts continue to use bearer tokens."
            : "Change the password used to gate the dashboard. Sign out all devices invalidates every existing session cookie; this device stays signed in.",
        }}
      />

      <form onSubmit={onSubmit} noValidate className="space-y-3 max-w-md">
        {!settingFirst ? (
          <div className="space-y-1.5">
            <label htmlFor="current-password" className="text-sm font-medium">
              Current password
            </label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              disabled={submitting}
            />
          </div>
        ) : null}
        <div className="space-y-1.5">
          <label htmlFor="new-password" className="text-sm font-medium">
            {settingFirst ? "Password" : "New password"}
          </label>
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            disabled={submitting}
          />
          <p className="text-xs text-muted-foreground">8 characters or more</p>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="confirm-password" className="text-sm font-medium">
            Confirm
          </label>
          <Input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            required
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            disabled={submitting}
          />
        </div>
        <FeedbackLine feedback={feedback} />
        <Button type="submit" disabled={submitting || !newPassword || !confirmPassword}>
          {submitLabel}
        </Button>
      </form>
    </section>
  );
}

export function AccessSessionsSection() {
  const { authRequired } = useAuthRequired();
  const [signingOutAll, setSigningOutAll] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);

  if (authRequired === null) return null;
  if (!authRequired) return null;

  const onSignOut = async () => {
    setFeedback(null);
    try {
      await logout();
      window.location.reload();
    } catch (err) {
      setFeedback({
        kind: "err",
        text: err instanceof Error ? err.message : "Sign out failed",
      });
    }
  };

  const onSignOutAll = async () => {
    setFeedback(null);
    setSigningOutAll(true);
    try {
      await signOutAllDevices();
      setFeedback({
        kind: "ok",
        text: "Other devices signed out. This device stays signed in.",
      });
    } catch (err) {
      setFeedback({
        kind: "err",
        text: err instanceof Error ? err.message : "Sign out all failed",
      });
    } finally {
      setSigningOutAll(false);
    }
  };

  return (
    <section className="space-y-2">
      <SettingsSectionHeader title="Sessions" />
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => void onSignOut()}>
          Sign out
        </Button>
        <Button variant="outline" onClick={() => void onSignOutAll()} disabled={signingOutAll}>
          {signingOutAll ? "Signing out…" : "Sign out all devices"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Sign out all devices rotates the session counter. Other devices land on the login screen on
        their next request; this device stays signed in.
      </p>
      <FeedbackLine feedback={feedback} />
    </section>
  );
}

export function AccessDevModeSection() {
  const { authRequired } = useAuthRequired();
  const { data: config } = useConfig();
  const updateConfig = useUpdateConfig();

  if (authRequired !== true) return null;

  const enabled = config?.auth_bypass_for_dev ?? false;

  return (
    <section className="space-y-3">
      <SettingsSectionHeader
        title="Disable login (development)"
        infoHint={{
          label: "About dev login bypass",
          content: (
            <p>
              When on, the API treats every request as authenticated — agents can hit any{" "}
              <code>/api/v1/*</code> endpoint without a cookie or bearer token. The password stays
              stored; turn this off to re-enable the login screen on the next request.
            </p>
          ),
        }}
      />
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-status-danger/30 bg-status-danger-muted/40 p-3">
        <div className="space-y-0.5">
          <p className="text-sm font-medium text-status-danger-accent">Disable login</p>
          <p className="text-xs text-muted-foreground">
            Skip the login screen on this network while keeping the password stored. Anyone reaching
            this URL can read your data while this is on. Intended for local development.
          </p>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={(next) => updateConfig.mutate({ auth_bypass_for_dev: next })}
          disabled={updateConfig.isPending}
          aria-label="Disable login (development)"
        />
      </div>
    </section>
  );
}
