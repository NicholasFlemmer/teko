import { useState, useRef } from "react";
import { Users, Camera } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { coachesAPI, uploadsAPI } from "@/services/api";

interface AddCoachModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function AddCoachModal({ open, onOpenChange, onSuccess }: AddCoachModalProps) {
  const [formData, setFormData] = useState({
    firstName: "",
    lastName: "",
    dob: "",
    email: "",
    mobile: "",
    emergencyName: "",
    emergencyRelationship: "",
    emergencyPhone: "",
  });
  const [profilePicture, setProfilePicture] = useState<string | null>(null);
  const [profilePictureUrl, setProfilePictureUrl] = useState<string | null>(null);
  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const resetForm = () => {
    // Revoke blob URL to prevent memory leak
    if (profilePicture?.startsWith('blob:')) {
      URL.revokeObjectURL(profilePicture);
    }
    setFormData({
      firstName: "",
      lastName: "",
      dob: "",
      email: "",
      mobile: "",
      emergencyName: "",
      emergencyRelationship: "",
      emergencyPhone: "",
    });
    setProfilePicture(null);
    setProfilePictureUrl(null);
    setUploadingPhoto(false);
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      setError(null);
      const payload = {
        first_name: formData.firstName,
        last_name: formData.lastName,
        dob: formData.dob || undefined,
        email: formData.email,
        phone_number: formData.mobile,
        emergency_name: formData.emergencyName || undefined,
        emergency_relationship: formData.emergencyRelationship || undefined,
        emergency_phone: formData.emergencyPhone || undefined,
        profile_picture: profilePictureUrl || undefined,
      };
      await coachesAPI.create(payload);
      resetForm();
      onOpenChange(false);
      onSuccess?.();
    } catch (err: any) {
      setError(err.message || "Failed to add coach");
    } finally {
      setSubmitting(false);
    }
  };

  const handleProfilePictureClick = () => {
    fileInputRef.current?.click();
  };

  const handleProfilePictureChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // Revoke previous blob URL before creating new one
      if (profilePicture?.startsWith('blob:')) {
        URL.revokeObjectURL(profilePicture);
      }
      setProfilePicture(URL.createObjectURL(file));
      try {
        setUploadingPhoto(true);
        setError(null);
        const result = await uploadsAPI.upload(file, 'profile-pictures');
        setProfilePictureUrl(result?.file?.public_url || null);
      } catch (err: any) {
        setError(err.message || "Failed to upload profile picture");
        setProfilePicture(null);
        setProfilePictureUrl(null);
      } finally {
        setUploadingPhoto(false);
      }
    }
  };

  const update = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <Dialog open={open} onOpenChange={(val) => { if (!val) resetForm(); onOpenChange(val); }}>
      <DialogContent className="sm:max-w-[500px] max-h-[90vh] p-0">
        <DialogHeader className="p-6 pb-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-success/10 flex items-center justify-center">
              <Users className="w-5 h-5 text-success" />
            </div>
            <div>
              <DialogTitle className="text-xl">Add New Coach</DialogTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Add a new coach to your team
              </p>
            </div>
          </div>
        </DialogHeader>

        <ScrollArea className="max-h-[calc(90vh-120px)]">
          <form onSubmit={handleSubmit} className="space-y-4 p-6 pt-4">
            {/* Error message */}
            {error && (
              <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            {/* Profile Picture */}
            <div className="flex flex-col items-center gap-2">
              <div
                onClick={handleProfilePictureClick}
                className="w-20 h-20 rounded-full bg-muted border-2 border-dashed border-border flex items-center justify-center cursor-pointer hover:border-primary/50 transition-colors overflow-hidden"
              >
                {profilePicture ? (
                  <img src={profilePicture} alt="Profile" className="w-full h-full object-cover" />
                ) : (
                  <Camera className="w-6 h-6 text-muted-foreground" />
                )}
              </div>
              <span className="text-xs text-muted-foreground">
                {uploadingPhoto ? "Uploading..." : "Profile Picture"}
              </span>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={handleProfilePictureChange}
              />
            </div>

            {/* Name Row */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="firstName">First Name</Label>
                <Input
                  id="firstName"
                  placeholder="e.g. John"
                  value={formData.firstName}
                  onChange={(e) => update("firstName", e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="lastName">Last Name</Label>
                <Input
                  id="lastName"
                  placeholder="e.g. Smith"
                  value={formData.lastName}
                  onChange={(e) => update("lastName", e.target.value)}
                />
              </div>
            </div>

            {/* DOB */}
            <div className="space-y-2">
              <Label htmlFor="dob">Date of Birth</Label>
              <Input
                id="dob"
                type="date"
                value={formData.dob}
                onChange={(e) => update("dob", e.target.value)}
              />
            </div>

            {/* Email */}
            <div className="space-y-2">
              <Label htmlFor="email">Email Address</Label>
              <Input
                id="email"
                type="email"
                placeholder="e.g. john@example.com"
                value={formData.email}
                onChange={(e) => update("email", e.target.value)}
              />
            </div>

            {/* Mobile */}
            <div className="space-y-2">
              <Label htmlFor="mobile">Mobile Number</Label>
              <Input
                id="mobile"
                type="tel"
                placeholder="+27 82 123 4567"
                value={formData.mobile}
                onChange={(e) => update("mobile", e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Include country code for SMS reminders
              </p>
            </div>

            {/* Emergency Contact Section */}
            <div className="space-y-3">
              <Label className="text-sm font-semibold">Emergency Contact</Label>
              <div className="rounded-lg border border-border p-3 space-y-3 bg-muted/30">
                <div className="space-y-2">
                  <Label htmlFor="emergencyName" className="text-xs">Name</Label>
                  <Input
                    id="emergencyName"
                    placeholder="e.g. Jane Smith"
                    value={formData.emergencyName}
                    onChange={(e) => update("emergencyName", e.target.value)}
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label htmlFor="emergencyRelationship" className="text-xs">Relationship</Label>
                    <Input
                      id="emergencyRelationship"
                      placeholder="e.g. Spouse"
                      value={formData.emergencyRelationship}
                      onChange={(e) => update("emergencyRelationship", e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="emergencyPhone" className="text-xs">Phone Number</Label>
                    <Input
                      id="emergencyPhone"
                      type="tel"
                      placeholder="+27 82 123 4567"
                      value={formData.emergencyPhone}
                      onChange={(e) => update("emergencyPhone", e.target.value)}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="flex gap-3 pt-4">
              <Button type="submit" className="flex-1" disabled={submitting || uploadingPhoto}>
                {submitting ? "Adding..." : "Add Coach"}
              </Button>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
                Cancel
              </Button>
            </div>
          </form>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
