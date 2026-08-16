// Geocoding helpers for resolving location coordinates used in check-in
// distance verification. Coordinates are returned as { latitude, longitude }.

export interface Coords {
  latitude: number;
  longitude: number;
}

const GOOGLE_MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as
  | string
  | undefined;

/**
 * Extract coordinates directly from a Google Maps URL without an API call.
 * Handles the common formats:
 *   - https://www.google.com/maps/@-33.918,18.423,15z
 *   - https://www.google.com/maps/place/.../@-33.918,18.423,17z
 *   - https://maps.google.com/?q=-33.918,18.423
 *   - https://www.google.com/maps?ll=-33.918,18.423
 *   - ...!3d-33.918!4d18.423...
 * Returns null when no coordinates can be parsed.
 */
export function extractCoordsFromMapsUrl(url?: string | null): Coords | null {
  if (!url) return null;

  const patterns: RegExp[] = [
    /@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/, // /@lat,lng
    /[?&](?:q|ll|sll|center)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/, // q=lat,lng
    /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/, // !3dlat!4dlng
  ];

  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) {
      const latitude = parseFloat(match[1]);
      const longitude = parseFloat(match[2]);
      if (!Number.isNaN(latitude) && !Number.isNaN(longitude)) {
        return { latitude, longitude };
      }
    }
  }

  return null;
}

/**
 * Geocode a free-text address to coordinates using the Google Maps
 * Geocoding API. Returns null when geocoding fails or no API key is set.
 */
export async function geocodeAddress(address?: string | null): Promise<Coords | null> {
  if (!address?.trim()) return null;

  if (!GOOGLE_MAPS_API_KEY) {
    console.warn(
      "VITE_GOOGLE_MAPS_API_KEY is not set — skipping address geocoding."
    );
    return null;
  }

  try {
    const url = `https://maps.googleapis.com/maps/api/geocode/json?address=${encodeURIComponent(
      address
    )}&key=${GOOGLE_MAPS_API_KEY}`;
    const res = await fetch(url);
    const data = await res.json();

    if (data.status === "OK" && data.results?.length) {
      const { lat, lng } = data.results[0].geometry.location;
      return { latitude: lat, longitude: lng };
    }

    console.warn("Geocoding failed:", data.status, data.error_message ?? "");
    return null;
  } catch (err) {
    console.error("Geocoding request error:", err);
    return null;
  }
}
