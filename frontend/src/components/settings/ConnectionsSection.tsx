import { useQueryClient } from "@tanstack/react-query";
import { Bot, Terminal, Sparkles, Gem, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Input } from "@/components/ui/input";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import {
  disconnectChatgpt,
  fetchChatgptLoginStatus,
  startChatgptLogin,
  testOpenAiConnection,
} from "@/lib/api";
import { queryKeys } from "@/lib/queryConfigs";
import { cn } from "@/lib/utils";

function DetectedStatus({ detected, label }: { detected: boolean; label: string }) {
  return detected ? (
    <span className="flex items-center gap-1.5 text-xs text-status-success">
      <CheckCircle className="h-3.5 w-3.5" /> {label} detected
    </span>
  ) : (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <XCircle className="h-3.5 w-3.5" /> Not detected
    </span>
  );
}

function ConnectionRow({
  icon: Icon,
  name,
  status,
  children,
}: {
  icon: typeof Bot;
  name: string;
  status: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border/50 p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
          <p className="text-sm font-medium">{name}</p>
        </div>
        {status}
      </div>
      {children}
    </div>
  );
}

export function ConnectionsSection() {
  const { data: config } = useConfig();
  const updateConfig = useUpdateConfig();
  const queryClient = useQueryClient();

  const [apiKey, setApiKey] = useState("");
  const [testState, setTestState] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [testError, setTestError] = useState("");
  const [chatgptState, setChatgptState] = useState<
    "idle" | "starting" | "waiting" | "disconnecting"
  >("idle");
  const [deviceLogin, setDeviceLogin] = useState<{ url: string; code: string } | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);

  const chatgptConnected = config?.chatgpt_oauth_connected ?? false;
  const chatgptEmail = config?.chatgpt_oauth_email ?? null;

  // While a device login is pending, poll until the Codex CLI confirms it.
  useEffect(() => {
    if (chatgptState !== "waiting") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await fetchChatgptLoginStatus();
        if (cancelled) return;
        if (status.connected) {
          setChatgptState("idle");
          setDeviceLogin(null);
          await queryClient.invalidateQueries({ queryKey: queryKeys.config() });
          toast.success("ChatGPT connected");
        } else if (!status.pending) {
          setChatgptState("idle");
          setDeviceLogin(null);
          setLoginError(
            status.error ?? "The sign-in did not complete. Connect again for a new code."
          );
        }
      } catch {
        // Transient fetch failure — keep polling.
      }
    };
    const id = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [chatgptState, queryClient]);

  const handleConnectChatgpt = async () => {
    setChatgptState("starting");
    setLoginError(null);
    try {
      const result = await startChatgptLogin();
      setDeviceLogin({ url: result.verification_url, code: result.user_code });
      setChatgptState("waiting");
    } catch (e) {
      setChatgptState("idle");
      setLoginError(e instanceof Error ? e.message : "Could not start the ChatGPT sign-in");
    }
  };

  const handleCancelChatgptLogin = async () => {
    setChatgptState("idle");
    setDeviceLogin(null);
    try {
      await disconnectChatgpt();
    } catch {
      // Cancelling a pending login is best-effort; the code expires on its own.
    }
  };

  const handleDisconnectChatgpt = async () => {
    setChatgptState("disconnecting");
    try {
      await disconnectChatgpt();
      await queryClient.invalidateQueries({ queryKey: queryKeys.config() });
      toast.success("ChatGPT disconnected");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setChatgptState("idle");
    }
  };

  const handleTestKey = async () => {
    if (!apiKey.trim()) return;
    setTestState("testing");
    setTestError("");
    try {
      const result = await testOpenAiConnection(apiKey.trim());
      if (result.ok) {
        setTestState("success");
        setApiKey("");
        // Refresh config to pick up the openai_enabled change.
        updateConfig.mutate({});
      } else {
        setTestState("error");
        setTestError(result.error ?? "Connection failed");
      }
    } catch {
      setTestState("error");
      setTestError("Network error");
    }
  };

  return (
    <section className="space-y-3">
      <SettingsSectionHeader
        title="Connections"
        infoHint={{
          label: "About connections",
          content:
            "How each AI provider signs in. A task in Task routing can only use a provider once it shows as connected here.",
        }}
      />
      <p className="text-sm text-muted-foreground">
        Sign in to the providers you want to route tasks to below.
      </p>

      {/* OpenAI API — API key + Test & Save */}
      <ConnectionRow
        icon={Bot}
        name="OpenAI API"
        status={
          config?.openai_enabled ? (
            <span className="flex items-center gap-1.5 text-xs text-status-success">
              <CheckCircle className="h-3.5 w-3.5" /> API key configured
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <XCircle className="h-3.5 w-3.5" /> API key required
            </span>
          )
        }
      >
        <div className="space-y-2">
          <label htmlFor="settings-openai-api-key" className="text-xs text-muted-foreground">
            API key
          </label>
          <div className="flex gap-2">
            <Input
              id="settings-openai-api-key"
              type="password"
              placeholder="sk-..."
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                setTestState("idle");
              }}
              className="font-mono text-sm"
            />
            <button
              onClick={handleTestKey}
              disabled={!apiKey.trim() || testState === "testing"}
              className={cn(
                "shrink-0 rounded-lg border px-4 py-2 text-sm font-medium transition-colors",
                testState === "success"
                  ? "border-status-success/30 bg-status-success/[0.04] text-status-success"
                  : testState === "error"
                    ? "border-status-danger/30 bg-status-danger/[0.04] text-status-danger"
                    : "border-border/50 hover:bg-accent",
                (!apiKey.trim() || testState === "testing") && "opacity-50 cursor-not-allowed"
              )}
            >
              {testState === "testing" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : testState === "success" ? (
                <span className="flex items-center gap-1.5">
                  <CheckCircle className="h-4 w-4" /> Saved
                </span>
              ) : (
                "Test & Save"
              )}
            </button>
          </div>
          {testState === "error" && <p className="text-xs text-destructive">{testError}</p>}
          {config?.openai_enabled && testState === "idle" && (
            <p className="text-xs text-muted-foreground">
              A key is already configured. Enter a new one to replace it.
            </p>
          )}
        </div>
      </ConnectionRow>

      {/* OpenAI Codex — ChatGPT device-code login */}
      <ConnectionRow
        icon={Sparkles}
        name="OpenAI Codex (ChatGPT account)"
        status={
          chatgptConnected ? (
            <span className="flex items-center gap-1.5 text-xs text-status-success">
              <CheckCircle className="h-3.5 w-3.5" />
              {chatgptEmail ? `Connected as ${chatgptEmail}` : "Connected"}
            </span>
          ) : config?.codex_available ? (
            <span className="flex items-center gap-1.5 text-xs text-status-success">
              <CheckCircle className="h-3.5 w-3.5" /> Signed in
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <XCircle className="h-3.5 w-3.5" /> Not connected
            </span>
          )
        }
      >
        {chatgptConnected ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Categorization and summaries bill against this ChatGPT subscription.
            </p>
            <button
              onClick={handleDisconnectChatgpt}
              disabled={chatgptState !== "idle"}
              className={cn(
                "shrink-0 rounded-lg border border-border/50 px-4 py-2 text-sm font-medium transition-colors hover:bg-accent",
                chatgptState !== "idle" && "opacity-50 cursor-not-allowed"
              )}
            >
              {chatgptState === "disconnecting" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Disconnect"
              )}
            </button>
          </div>
        ) : chatgptState === "waiting" && deviceLogin ? (
          <div className="space-y-3">
            <div className="space-y-0.5">
              <p className="text-sm font-medium">Finish signing in</p>
              <p className="text-xs text-muted-foreground">
                Open{" "}
                <a
                  href={deviceLogin.url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2 hover:text-foreground"
                >
                  {deviceLogin.url.replace("https://", "")}
                </a>{" "}
                and enter this one-time code.
              </p>
            </div>
            <p
              data-testid="chatgpt-device-code"
              className="select-all rounded-lg border border-border/50 bg-accent px-4 py-2 text-center font-mono text-lg tracking-widest"
            >
              {deviceLogin.code}
            </p>
            <div className="flex items-center justify-between gap-3">
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Waiting for the sign-in to complete. The code expires in 15 minutes.
              </p>
              <button
                onClick={handleCancelChatgptLogin}
                className="shrink-0 rounded-lg border border-border/50 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Use your existing ChatGPT Plus or Pro subscription instead of an API key.
            </p>
            <button
              onClick={handleConnectChatgpt}
              disabled={chatgptState !== "idle"}
              className={cn(
                "rounded-lg border border-primary bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90",
                chatgptState !== "idle" && "opacity-50 cursor-not-allowed"
              )}
            >
              {chatgptState === "starting" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Connect ChatGPT"
              )}
            </button>
            {loginError && <p className="text-xs text-destructive">{loginError}</p>}
            <p className="text-xs text-muted-foreground">
              Signs in with the Codex CLI's device code, so tasks routed to Codex bill against your
              ChatGPT Plus or Pro subscription. May stop working if OpenAI changes the flow.
            </p>
            <p className="text-xs text-muted-foreground">
              Prefer the terminal? Run{" "}
              <code className="font-mono text-xs">codex login --device-auth</code> — the app picks
              up that session automatically.
            </p>
          </div>
        )}
      </ConnectionRow>

      {/* Claude Code — detection only */}
      <ConnectionRow
        icon={Terminal}
        name="Claude Code"
        status={
          <DetectedStatus detected={config?.claude_cli_available ?? false} label="Claude Code" />
        }
      >
        <p className="text-xs text-muted-foreground">
          Claude Code has no in-app login. Authenticate via the VS Code extension, or run{" "}
          <code className="font-mono text-xs">claude</code> once in your terminal and complete the
          sign-in flow. The app invokes the CLI headlessly once you're signed in.
        </p>
      </ConnectionRow>

      {/* Google Gemini — detection only */}
      <ConnectionRow
        icon={Gem}
        name="Google Gemini"
        status={
          <DetectedStatus detected={config?.gemini_cli_available ?? false} label="Google Gemini" />
        }
      >
        <p className="text-xs text-muted-foreground">
          Google Gemini signs in via its own CLI. Run{" "}
          <code className="font-mono text-xs">gemini</code> once in your terminal and complete the
          web auth flow, or set <code className="font-mono text-xs">GEMINI_API_KEY</code>. The app
          invokes <code className="font-mono text-xs">gemini -p</code> headlessly once you're signed
          in.
        </p>
      </ConnectionRow>
    </section>
  );
}
