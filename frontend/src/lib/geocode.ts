// Geocoding helpers for resolving location coordinates used in check-in
// distance verification. Coordinates are returned as { latitude, longitude }.

import { locationsAPI } from "@/services/api";

export interface Coords {
  latitude: number;
  longitude: number;
}

// Google Maps links are read by the backend (it uses the place marker, never the
// map centre) -- the browser deliberately does not read coordinates from links.

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
