// Geocoding helpers for resolving location coordinates used in check-in
// distance verification. Coordinates are returned as { latitude, longitude }.

import { locationsAPI } from "@/services/api";

export interface Coords {
  latitude: number;
  longitude: number;
}

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
 * Geocode a free-text address to coordinates via the backend's
 * /api/locations/geocode endpoint (which holds the Google Maps API key
 * server-side, not the browser). Returns null when geocoding fails.
 */
export async function geocodeAddress(address?: string | null): Promise<Coords | null> {
  if (!address?.trim()) return null;

  try {
    const data = await locationsAPI.geocode(address);
    return { latitude: data.latitude, longitude: data.longitude };
  } catch (err) {
    console.warn("Geocoding failed:", err);
    return null;
  }
}
