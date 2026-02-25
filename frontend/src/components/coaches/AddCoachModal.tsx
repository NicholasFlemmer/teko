import { useState, useRef } from "react";
import { Users, Upload, X, FileText, Image, Camera } from "lucide-react";
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

interface MockFile {
  id: string;
  name: string;
  type: string;
  size: string;
}

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
  const [mockFiles, setMockFiles] = useState<MockFile[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const resetForm = () => {
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
    setMockFiles([]);
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
      setProfilePicture(URL.createObjectURL(file));
      try {
        setUploadingPhoto(true);
        setError(null);
        const result = await uploadsAPI.upload(file, 'coach-photos');
        setProfilePictureUrl(result.file.public_url);
      } catch (err: any) {
        setError(err.message || "Failed to upload profile picture");
        setProfilePicture(null);
        setProfilePictureUrl(null);
      } finally {
        setUploadingPhoto(false);
      }
    }
  };

  const handleFileSelect = () => {
    const mockNewFile: MockFile = {
      id: Date.now().toString(),
      name: `document_${mockFiles.length + 1}.pdf`,
      type: "application/pdf",
      size: "245 KB",
    };
    setMockFiles([...mockFiles, mockNewFile]);
  };

  const removeFile = (id: string) => {
    setMockFiles(mockFiles.filter((f) => f.id !== id));
  };

  const getFileIcon = (type: string) => {
    if (type.startsWith("image/")) return <Image className="w-4 h-4" />;
    return <FileText className="w-4 h-4" />;
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

            {/* Documents Upload */}
            <div className="space-y-2">
              <Label>Documents</Label>
              <div
                onClick={handleFileSelect}
                className="border-2 border-dashed border-border rounded-lg p-4 text-center cursor-pointer hover:border-primary/50 hover:bg-muted/50 transition-colors"
              >
                <Upload className="w-6 h-6 mx-auto text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">Click to upload files</p>
                <p className="text-xs text-muted-foreground mt-1">PDF, images, or documents</p>
              </div>

              {mockFiles.length > 0 && (
                <div className="space-y-2 mt-3">
                  {mockFiles.map((file) => (
                    <div
                      key={file.id}
                      className="flex items-center gap-3 p-2 rounded-lg bg-muted/50 border border-border"
                    >
                      <div className="w-8 h-8 rounded bg-primary/10 flex items-center justify-center text-primary">
                        {getFileIcon(file.type)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{file.name}</p>
                        <p className="text-xs text-muted-foreground">{file.size}</p>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        onClick={() => removeFile(file.id)}
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
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
