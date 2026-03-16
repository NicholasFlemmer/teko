import { useState, useEffect } from "react";
import { MapPin, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { locationsAPI } from "@/services/api";
import { geocodeAddress, extractCoordsFromMapsUrl } from "@/lib/geocode";

interface AddLocationModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLocationAdded?: () => void;
}

export function AddLocationModal({ open, onOpenChange, onLocationAdded }: AddLocationModalProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formData, setFormData] = useState({
    name: "",
    address: "",
    googleMapsLink: "",
    notes: "",
  });

  // Reset form when modal opens
  useEffect(() => {
    if (open) {
      setFormData({ name: "", address: "", googleMapsLink: "", notes: "" });
      setError(null);
    }
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      setError(null);

      // Geocode address to get lat/lng for check-in distance verification
      const coords =
        extractCoordsFromMapsUrl(formData.googleMapsLink) ||
        (await geocodeAddress(formData.address));

      await locationsAPI.create({
        name: formData.name,
        address: formData.address,
        google_maps_link: formData.googleMapsLink || undefined,
        notes: formData.notes || undefined,
        ...(coords && { latitude: coords.latitude, longitude: coords.longitude }),
      });
      onOpenChange(false);
      setFormData({
        name: "",
        address: "",
        googleMapsLink: "",
        notes: "",
      });
      onLocationAdded?.();
    } catch (err: any) {
      console.error("Failed to create location:", err);
      setError(err.message || "Failed to create location");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-info/10 flex items-center justify-center">
              <MapPin className="w-5 h-5 text-info" />
            </div>
            <div>
              <DialogTitle className="text-xl">Add New Location</DialogTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Add a venue for coaching sessions
              </p>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          {error && (
            <div className="bg-destructive/10 text-destructive text-sm p-3 rounded-lg">{error}</div>
          )}
          <div className="space-y-2">
            <Label htmlFor="name">Location Name</Label>
            <Input
              id="name"
              placeholder="e.g. Main Hall"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="googleMapsLink">Google Maps Link *</Label>
            <Input
              id="googleMapsLink"
              type="url"
              placeholder="Paste a Google Maps link for the venue"
              value={formData.googleMapsLink}
              onChange={(e) => setFormData({ ...formData, googleMapsLink: e.target.value })}
              required
            />
            <p className="text-xs text-muted-foreground">
              This is used to determine the venue's GPS coordinates for check-in
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="address">Address (optional)</Label>
            <Textarea
              id="address"
              placeholder="e.g. 123 Main Street, Johannesburg, 2000"
              value={formData.address}
              onChange={(e) => setFormData({ ...formData, address: e.target.value })}
              rows={2}
            />
          </div>

          {/* Map Preview */}
          {formData.address.trim() && import.meta.env.VITE_GOOGLE_MAPS_API_KEY && (
            <div className="space-y-2">
              <Label>Map Preview</Label>
              <div className="rounded-lg border border-border overflow-hidden">
                <iframe
                  title="Location Preview"
                  width="100%"
                  height="200"
                  style={{ border: 0 }}
                  loading="lazy"
                  referrerPolicy="no-referrer-when-downgrade"
                  src={`https://www.google.com/maps/embed/v1/place?key=${import.meta.env.VITE_GOOGLE_MAPS_API_KEY}&q=${encodeURIComponent(formData.address)}`}
                  allowFullScreen
                />
              </div>
            </div>
          )}


          <div className="space-y-2">
            <Label htmlFor="notes">Notes (Optional)</Label>
            <Textarea
              id="notes"
              placeholder="e.g. Parking available, indoor and outdoor areas..."
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              rows={2}
            />
          </div>

          <div className="flex gap-3 pt-4">
            <Button type="submit" className="flex-1" disabled={submitting}>
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Adding...
                </>
              ) : (
                "Add Location"
              )}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
