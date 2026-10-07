/** Only API failures are intentionally exercised by these browser scenarios.
 * A failed JS/CSS/document load must not be dismissed as API error noise.
 */
export function isApiResourceNoise(text: string): boolean {
  if (!text.startsWith("Failed to load resource:")) return false;
  const separator = text.lastIndexOf(" @ ");
  if (separator < 0) return false;
  try {
    const url = new URL(text.slice(separator + 3));
    return (url.protocol === "http:" || url.protocol === "https:") && url.pathname.startsWith("/api/");
  } catch {
    return false;
  }
}
