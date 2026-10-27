function base64Url(bytes: Uint8Array): string {
  let s = "";
  bytes.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomString(bytes = 32): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return base64Url(buf);
}

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

const KEY = "aistack.pkce";

export interface PkceConfig {
  apiBase: string;
  clientId: string;
  redirectUri: string;
}

/** Start the authorization-code + PKCE flow by redirecting to the IdP. */
export async function beginLogin(cfg: PkceConfig, loginHint: string): Promise<void> {
  const verifier = randomString(48);
  const state = randomString(12);
  sessionStorage.setItem(KEY, JSON.stringify({ verifier, state }));
  const q = new URLSearchParams({
    response_type: "code",
    client_id: cfg.clientId,
    redirect_uri: cfg.redirectUri,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
    state,
    login_hint: loginHint,
  });
  window.location.assign(`${cfg.apiBase}/idp/authorize?${q.toString()}`);
}

/** Finish the flow on the callback page. Returns the access token. */
export async function completeLogin(cfg: PkceConfig, search: string): Promise<string> {
  const params = new URLSearchParams(search);
  const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "null") as {
    verifier: string;
    state: string;
  } | null;
  sessionStorage.removeItem(KEY);
  const code = params.get("code");
  if (!saved || !code || params.get("state") !== saved.state) {
    throw new Error("Login response did not match the request that started it.");
  }
  const res = await fetch(`${cfg.apiBase}/idp/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      code_verifier: saved.verifier,
      client_id: cfg.clientId,
      redirect_uri: cfg.redirectUri,
    }),
  });
  if (!res.ok) throw new Error(`Token exchange failed with status ${res.status}`);
  const body = (await res.json()) as { access_token: string };
  return body.access_token;
}
