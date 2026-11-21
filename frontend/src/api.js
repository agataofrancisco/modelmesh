// Cliente mínimo da API de administração. O token vive só em sessionStorage (por separador).
const TOKEN_KEY = "modelmesh.adminToken";

export function getToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(value) {
  try {
    sessionStorage.setItem(TOKEN_KEY, value);
  } catch {
    // Armazenamento indisponível: o token fica só em memória nesta sessão.
  }
}

export async function api(path, { method = "GET", body, token = getToken() } = {}) {
  if (path.startsWith("/admin") && !token) {
    // Sem token não se envia o pedido: evita 401 em série ao abrir o painel.
    throw new Error("sem_token: introduza o token de administração");
  }
  const headers = { "content-type": "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message = payload?.error?.message || `HTTP ${response.status}`;
    const code = payload?.error?.code || "erro";
    throw new Error(`${code}: ${message}`);
  }
  return payload;
}
