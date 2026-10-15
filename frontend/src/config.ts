const configuredApiUrl = import.meta.env.VITE_API_BASE_URL;

if (!configuredApiUrl) {
  throw new Error("Set VITE_API_BASE_URL in the frontend environment.");
}

const parsedApiUrl = new URL(configuredApiUrl);

if (
  !["http:", "https:"].includes(parsedApiUrl.protocol) ||
  parsedApiUrl.username ||
  parsedApiUrl.password ||
  parsedApiUrl.search ||
  parsedApiUrl.hash
) {
  throw new Error("VITE_API_BASE_URL must be an HTTP(S) URL without credentials or query parameters.");
}

export const apiBaseUrl = parsedApiUrl.href.replace(/\/+$/, "");
