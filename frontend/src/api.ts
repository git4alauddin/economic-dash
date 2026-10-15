import { apiBaseUrl } from "./config";

export async function checkApiConnection(signal: AbortSignal): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/`, { signal });

  if (!response.ok) {
    throw new Error("The API request failed.");
  }

  const payload: unknown = await response.json();

  if (
    typeof payload !== "object" ||
    payload === null ||
    !("message" in payload) ||
    typeof payload.message !== "string"
  ) {
    throw new Error("The API returned an unexpected response.");
  }
}
