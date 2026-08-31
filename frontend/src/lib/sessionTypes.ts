/**
 * Formats a raw session `type` value for display.
 *
 * Absent/blank -> "Practice" (matches the backend's own default of
 * 'practice' for sessions created without an explicit type, e.g. the
 * WhatsApp /session flow). Otherwise, hyphens/underscores become spaces
 * and each word is title-cased -- this is what lets a free-text value
 * like "coach-academy-coaching-course" display correctly instead of
 * being hardcoded to a fixed set of known types.
 */
export function formatSessionType(type?: string): string {
  const trimmed = (type ?? "").trim();
  if (!trimmed) {
    return "Practice";
  }

  return trimmed
    .replace(/[-_]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}
