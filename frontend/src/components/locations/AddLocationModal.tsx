import { useState, useRef } from "react";
import { MapPin, Camera, X, ImagePlus, Loader2 } from "lucide-react";
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

interface AddLocationModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLocationAdded?: () => void;
}

export function AddLocationModal({ open, onOpenChange, onLocationAdded }: AddLocationModalProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [photos, setPhotos] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [formData, setFormData] = useState({
    name: "",
    address: "",
    googleMapsLink: "",
    notes: "",
  });

  const handlePhotosChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    Array.from(files).forEach((file) => {
      const reader = new FileReader();
      reader.onloadend = () => setPhotos((prev) => [...prev, reader.result as string]);
      reader.readAsDataURL(file);
    });
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const removePhoto = (index: number) => {
    setPhotos((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      await locationsAPI.create({
        name: formData.name,
        address: formData.address,
        google_maps_link: formData.googleMapsLink || undefined,
        notes: formData.notes || undefined,
      });
      onOpenChange(false);
      setPhotos([]);
      setFormData({
        name: "",
        address: "",
        googleMapsLink: "",
        notes: "",
      });
      onLocationAdded?.();
    } catch (err) {
      console.error("Failed to create location:", err);
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
            <Label htmlFor="address">Full Address</Label>
            <Textarea
              id="address"
              placeholder="e.g. 123 Main Street, Johannesburg, 2000"
              value={formData.address}
              onChange={(e) => setFormData({ ...formData, address: e.target.value })}
              rows={2}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="googleMapsLink">Google Maps Link</Label>
            <Input
              id="googleMapsLink"
              type="url"
              placeholder="e.g. https://maps.google.com/..."
              value={formData.googleMapsLink}
              onChange={(e) => setFormData({ ...formData, googleMapsLink: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              Paste a Google Maps share link for the location
            </p>
          </div>

          {/* Map Preview */}
          {formData.address.trim() && (
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
            <Label>Photos (Optional)</Label>
            <div className="flex flex-wrap gap-2">
              {photos.map((photo, index) => (
                <div key={index} className="relative w-16 h-16 rounded-md overflow-hidden border border-border">
                  <img src={photo} alt={`Location photo ${index + 1}`} className="w-full h-full object-cover" />
                  <button
                    type="button"
                    className="absolute top-0 right-0 w-4 h-4 bg-destructive text-destructive-foreground rounded-full flex items-center justify-center"
                    onClick={() => removePhoto(index)}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="w-16 h-16 rounded-md border-2 border-dashed border-border hover:border-primary transition-colors flex items-center justify-center bg-muted"
                onClick={() => fileInputRef.current?.click()}
              >
                <ImagePlus className="w-5 h-5 text-muted-foreground" />
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={handlePhotosChange}
            />
          </div>

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
