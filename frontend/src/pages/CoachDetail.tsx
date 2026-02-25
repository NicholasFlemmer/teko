import { useState, useRef, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Mail,
  Phone,
  Calendar,
  MapPin,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Edit,
  MessageSquare,
  FileText,
  Image,
  Download,
  Upload,
  Eye,
  Camera,
  Save,
  X,
  Heart
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MainLayout } from "@/components/layout/MainLayout";
import { coachesAPI, uploadsAPI } from "@/services/api";

export default function CoachDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const docFileInputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const [uploadingDoc, setUploadingDoc] = useState(false);

  // Raw coach data from API
  const [coachData, setCoachData] = useState<any>(null);

  const [formData, setFormData] = useState({
    firstName: "",
    lastName: "",
    dob: "",
    email: "",
    mobile: "",
    emergencyName: "",
    emergencyRelationship: "",
    emergencyPhone: "",
    notes: "",
  });
  const [profilePicture, setProfilePicture] = useState<string | null>(null);

  // Fetch coach from API
  useEffect(() => {
    if (!id) return;
    const fetchCoach = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await coachesAPI.getOne(id);
        if (response.success && response.coach) {
          const c = response.coach;
          setCoachData(c);
          setFormData({
            firstName: c.first_name || "",
            lastName: c.last_name || "",
            dob: c.dob || "",
            email: c.email || "",
            mobile: c.phone_number || "",
            emergencyName: c.emergency_name || "",
            emergencyRelationship: c.emergency_relationship || "",
            emergencyPhone: c.emergency_phone || "",
            notes: c.notes || "",
          });
          setProfilePicture(c.profile_picture || null);
        }
      } catch (err: any) {
        setError(err.message || "Failed to load coach");
      } finally {
        setLoading(false);
      }
    };
    fetchCoach();
  }, [id]);

  // Derived display values
  const color = "bg-primary";
  const joinedDate = coachData?.joined_date || "";
  const totalSessions = coachData?.totalSessions ?? 0;
  const checkedIn = coachData?.checkedIn ?? 0;
  const late = coachData?.late ?? 0;
  const missed = coachData?.missed ?? 0;
  const locations: string[] = coachData?.locations ?? [];
  const upcomingSchedule: any[] = coachData?.upcomingSchedule ?? [];
  const recentCheckIns: any[] = coachData?.recentCheckIns ?? [];
  const documents: any[] = coachData?.documents ?? [];

  const attendanceRate = totalSessions > 0 ? Math.round((checkedIn / totalSessions) * 100) : 0;

  const update = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async () => {
    if (!id) return;
    try {
      setSaving(true);
      const payload: any = {
        first_name: formData.firstName,
        last_name: formData.lastName,
        dob: formData.dob,
        email: formData.email,
        phone_number: formData.mobile,
        emergency_name: formData.emergencyName,
        emergency_relationship: formData.emergencyRelationship,
        emergency_phone: formData.emergencyPhone,
        notes: formData.notes,
        profile_picture: profilePicture || undefined,
      };
      const response = await coachesAPI.update(id, payload);
      if (response.success && response.coach) {
        const c = response.coach;
        setCoachData(c);
        setFormData({
          firstName: c.first_name || "",
          lastName: c.last_name || "",
          dob: c.dob || "",
          email: c.email || "",
          mobile: c.phone_number || "",
          emergencyName: c.emergency_name || "",
          emergencyRelationship: c.emergency_relationship || "",
          emergencyPhone: c.emergency_phone || "",
          notes: c.notes || "",
        });
      }
      setIsEditing(false);
    } catch (err: any) {
      console.error("Failed to save coach:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (coachData) {
      const c = coachData;
      setFormData({
        firstName: c.first_name || "",
        lastName: c.last_name || "",
        dob: c.dob || "",
        email: c.email || "",
        mobile: c.phone_number || "",
        emergencyName: c.emergency_name || "",
        emergencyRelationship: c.emergency_relationship || "",
        emergencyPhone: c.emergency_phone || "",
        notes: c.notes || "",
      });
      setProfilePicture(c.profile_picture || null);
    }
    setIsEditing(false);
  };

  const handleProfilePictureChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const previewUrl = URL.createObjectURL(file);
      setProfilePicture(previewUrl);
      try {
        setUploadingPhoto(true);
        const result = await uploadsAPI.upload(file, 'coach-photos');
        setProfilePicture(result.file.public_url);
        // Auto-save the profile picture to the coach record
        if (id) {
          await coachesAPI.update(id, { profile_picture: result.file.public_url });
        }
      } catch (err: any) {
        console.error("Failed to upload profile picture:", err);
        setProfilePicture(coachData?.profile_picture || null);
      } finally {
        setUploadingPhoto(false);
      }
    }
  };

  const handleDocumentUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && id) {
      try {
        setUploadingDoc(true);
        const result = await uploadsAPI.upload(file, 'coach-documents');
        // Add the document reference to the coach record
        const newDoc = {
          id: Date.now().toString(),
          name: result.file.file_name,
          type: result.file.content_type,
          size: result.file.size ? `${Math.round(result.file.size / 1024)} KB` : 'Unknown',
          url: result.file.public_url,
          file_path: result.file.file_path,
          uploadedAt: new Date().toISOString(),
        };
        const updatedDocs = [...(coachData?.documents || []), newDoc];
        const response = await coachesAPI.update(id, { documents: updatedDocs });
        if (response.success && response.coach) {
          setCoachData(response.coach);
        }
      } catch (err: any) {
        console.error("Failed to upload document:", err);
      } finally {
        setUploadingDoc(false);
        // Reset the input so the same file can be selected again
        if (docFileInputRef.current) {
          docFileInputRef.current.value = '';
        }
      }
    }
  };

  const fullName = `${formData.firstName} ${formData.lastName}`.trim();
  const initials = `${formData.firstName?.[0] || ""}${formData.lastName?.[0] || ""}`.toUpperCase();

  if (loading) {
    return (
      <MainLayout>
        <div className="space-y-6">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => navigate("/coaches")}>
              <ArrowLeft className="w-5 h-5" />
            </Button>
            <div className="flex-1">
              <div className="h-7 w-48 bg-muted rounded animate-pulse" />
              <div className="h-4 w-24 bg-muted rounded animate-pulse mt-2" />
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="space-y-4">
              <div className="bg-card rounded-xl border border-border p-6 shadow-card animate-pulse">
                <div className="flex items-center gap-4 mb-6">
                  <div className="w-16 h-16 rounded-full bg-muted" />
                  <div className="space-y-2">
                    <div className="h-5 w-32 bg-muted rounded" />
                    <div className="h-4 w-16 bg-muted rounded" />
                  </div>
                </div>
                <div className="space-y-4">
                  <div className="h-4 w-full bg-muted rounded" />
                  <div className="h-4 w-3/4 bg-muted rounded" />
                  <div className="h-4 w-2/3 bg-muted rounded" />
                </div>
              </div>
            </div>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="bg-card rounded-xl border border-border p-4 shadow-card animate-pulse">
                    <div className="h-8 w-12 bg-muted rounded mx-auto mb-2" />
                    <div className="h-3 w-20 bg-muted rounded mx-auto" />
                  </div>
                ))}
              </div>
            </div>
            <div className="space-y-4">
              <div className="bg-card rounded-xl border border-border p-5 shadow-card animate-pulse">
                <div className="h-5 w-40 bg-muted rounded mb-4" />
                <div className="space-y-3">
                  <div className="h-16 bg-muted rounded" />
                  <div className="h-16 bg-muted rounded" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </MainLayout>
    );
  }

  if (error) {
    return (
      <MainLayout>
        <div className="space-y-6">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => navigate("/coaches")}>
              <ArrowLeft className="w-5 h-5" />
            </Button>
            <div className="flex-1">
              <h1 className="page-title">Coach Not Found</h1>
            </div>
          </div>
          <div className="text-center py-12">
            <p className="text-destructive mb-4">{error}</p>
            <Button variant="outline" onClick={() => navigate("/coaches")}>
              Back to Coaches
            </Button>
          </div>
        </div>
      </MainLayout>
    );
  }

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate("/coaches")}>
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div className="flex-1">
            <h1 className="page-title">{fullName || "Coach"}</h1>
            <p className="page-subtitle">Coach Details</p>
          </div>
          {isEditing ? (
            <div className="flex gap-2">
              <Button variant="outline" className="gap-2" onClick={handleCancel} disabled={saving}>
                <X className="w-4 h-4" />
                Cancel
              </Button>
              <Button className="gap-2" onClick={handleSave} disabled={saving}>
                <Save className="w-4 h-4" />
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          ) : (
            <>
              <Button variant="outline" className="gap-2">
                <MessageSquare className="w-4 h-4" />
                Send Message
              </Button>
              <Button className="gap-2" onClick={() => setIsEditing(true)}>
                <Edit className="w-4 h-4" />
                Edit Coach
              </Button>
            </>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column - Profile & Contact */}
          <div className="space-y-4">
            {/* Profile card */}
            <div className="bg-card rounded-xl border border-border p-6 shadow-card">
              {isEditing ? (
                <div className="space-y-4">
                  {/* Profile Picture Edit */}
                  <div className="flex flex-col items-center gap-2">
                    <div
                      onClick={() => fileInputRef.current?.click()}
                      className="w-20 h-20 rounded-full bg-muted border-2 border-dashed border-border flex items-center justify-center cursor-pointer hover:border-primary/50 transition-colors overflow-hidden"
                    >
                      {profilePicture ? (
                        <img src={profilePicture} alt="Profile" className="w-full h-full object-cover" />
                      ) : (
                        <Camera className="w-6 h-6 text-muted-foreground" />
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {uploadingPhoto ? "Uploading..." : "Click to change photo"}
                    </span>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={handleProfilePictureChange}
                    />
                  </div>

                  {/* Name */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="firstName" className="text-xs">First Name</Label>
                      <Input id="firstName" value={formData.firstName} onChange={(e) => update("firstName", e.target.value)} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="lastName" className="text-xs">Last Name</Label>
                      <Input id="lastName" value={formData.lastName} onChange={(e) => update("lastName", e.target.value)} />
                    </div>
                  </div>

                  {/* DOB */}
                  <div className="space-y-1.5">
                    <Label htmlFor="dob" className="text-xs">Date of Birth</Label>
                    <Input id="dob" type="date" value={formData.dob} onChange={(e) => update("dob", e.target.value)} />
                  </div>

                  {/* Email */}
                  <div className="space-y-1.5">
                    <Label htmlFor="email" className="text-xs">Email</Label>
                    <Input id="email" type="email" value={formData.email} onChange={(e) => update("email", e.target.value)} />
                  </div>

                  {/* Mobile */}
                  <div className="space-y-1.5">
                    <Label htmlFor="mobile" className="text-xs">Mobile</Label>
                    <Input id="mobile" type="tel" value={formData.mobile} onChange={(e) => update("mobile", e.target.value)} />
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-4 mb-6">
                    {profilePicture ? (
                      <img src={profilePicture} alt={fullName} className="w-16 h-16 rounded-full object-cover" />
                    ) : (
                      <div className={`w-16 h-16 rounded-full ${color} avatar-initials text-xl`}>
                        {initials}
                      </div>
                    )}
                    <div>
                      <h2 className="text-xl font-semibold text-foreground">{fullName}</h2>
                      <span className="badge-coach">Coach</span>
                    </div>
                  </div>

                  <div className="space-y-4">
                    {formData.dob && (
                      <div className="flex items-center gap-3 text-muted-foreground">
                        <Calendar className="w-5 h-5 flex-shrink-0" />
                        <span className="text-foreground">
                          DOB: {new Date(formData.dob).toLocaleDateString('en-ZA', { year: 'numeric', month: 'long', day: 'numeric' })}
                        </span>
                      </div>
                    )}
                    <div className="flex items-center gap-3 text-muted-foreground">
                      <Mail className="w-5 h-5 flex-shrink-0" />
                      <span className="text-foreground">{formData.email}</span>
                    </div>
                    <div className="flex items-center gap-3 text-muted-foreground">
                      <Phone className="w-5 h-5 flex-shrink-0" />
                      <span className="text-foreground">{formData.mobile}</span>
                    </div>
                    {joinedDate && (
                      <div className="flex items-center gap-3 text-muted-foreground">
                        <Calendar className="w-5 h-5 flex-shrink-0" />
                        <span className="text-foreground">Joined {new Date(joinedDate).toLocaleDateString('en-ZA', { year: 'numeric', month: 'long', day: 'numeric' })}</span>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* Emergency Contact */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-3 flex items-center gap-2">
                <Heart className="w-4 h-4 text-destructive" />
                Emergency Contact
              </h3>
              {isEditing ? (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="emergencyName" className="text-xs">Name</Label>
                    <Input id="emergencyName" value={formData.emergencyName} onChange={(e) => update("emergencyName", e.target.value)} />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="emergencyRelationship" className="text-xs">Relationship</Label>
                      <Input id="emergencyRelationship" value={formData.emergencyRelationship} onChange={(e) => update("emergencyRelationship", e.target.value)} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="emergencyPhone" className="text-xs">Phone</Label>
                      <Input id="emergencyPhone" type="tel" value={formData.emergencyPhone} onChange={(e) => update("emergencyPhone", e.target.value)} />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 text-sm">
                  <p className="text-foreground font-medium">{formData.emergencyName || "Not set"}</p>
                  <p className="text-muted-foreground">{formData.emergencyRelationship || "Not set"}</p>
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Phone className="w-4 h-4" />
                    <span>{formData.emergencyPhone || "Not set"}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Locations */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-3">Locations</h3>
              <div className="space-y-2">
                {locations.length > 0 ? (
                  locations.map((location: string, index: number) => (
                    <div key={index} className="flex items-center gap-2 text-sm text-muted-foreground">
                      <MapPin className="w-4 h-4" />
                      <span>{location}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground">No locations assigned</p>
                )}
              </div>
            </div>

            {/* Documents */}
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Documents</h3>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5 h-8"
                  disabled={uploadingDoc}
                  onClick={() => docFileInputRef.current?.click()}
                >
                  <Upload className="w-3.5 h-3.5" />
                  {uploadingDoc ? "Uploading..." : "Upload"}
                </Button>
                <input
                  ref={docFileInputRef}
                  type="file"
                  className="hidden"
                  onChange={handleDocumentUpload}
                />
              </div>

              {documents && documents.length > 0 ? (
                <div className="space-y-2">
                  {documents.map((doc: any) => (
                    <div
                      key={doc.id}
                      className="flex items-center gap-3 p-3 rounded-lg bg-muted/50 border border-border hover:bg-muted transition-colors group"
                    >
                      <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center text-primary flex-shrink-0">
                        {doc.type?.startsWith("image/") ? (
                          <Image className="w-4 h-4" />
                        ) : (
                          <FileText className="w-4 h-4" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{doc.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {doc.size} • {new Date(doc.uploadedAt).toLocaleDateString('en-ZA', { month: 'short', day: 'numeric', year: 'numeric' })}
                        </p>
                      </div>
                      <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        {doc.url && (
                          <Button variant="ghost" size="icon" className="h-8 w-8" asChild>
                            <a href={doc.url} target="_blank" rel="noopener noreferrer">
                              <Eye className="w-4 h-4" />
                            </a>
                          </Button>
                        )}
                        {doc.url && (
                          <Button variant="ghost" size="icon" className="h-8 w-8" asChild>
                            <a href={doc.url} download={doc.name}>
                              <Download className="w-4 h-4" />
                            </a>
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-6">
                  <FileText className="w-8 h-8 text-muted-foreground/30 mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">No documents uploaded</p>
                </div>
              )}
            </div>
          </div>

          {/* Middle column - Attendance stats */}
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-card rounded-xl border border-border p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-foreground">{totalSessions}</p>
                <p className="text-sm text-muted-foreground">Total Sessions</p>
              </div>
              <div className="bg-card rounded-xl border border-success/30 p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-success">{attendanceRate}%</p>
                <p className="text-sm text-muted-foreground">Attendance Rate</p>
              </div>
              <div className="bg-card rounded-xl border border-warning/30 p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-warning">{late}</p>
                <p className="text-sm text-muted-foreground">Late Check-ins</p>
              </div>
              <div className="bg-card rounded-xl border border-destructive/30 p-4 shadow-card text-center">
                <p className="text-3xl font-bold text-destructive">{missed}</p>
                <p className="text-sm text-muted-foreground">Missed Sessions</p>
              </div>
            </div>

            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Recent Check-ins</h3>
              <div className="space-y-3">
                {recentCheckIns.length > 0 ? (
                  recentCheckIns.map((checkin: any) => (
                    <div key={checkin.id} className="flex items-center justify-between p-3 rounded-lg bg-muted/50">
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {new Date(checkin.date).toLocaleDateString('en-ZA', { weekday: 'short', month: 'short', day: 'numeric' })}
                        </p>
                        <p className="text-xs text-muted-foreground">{checkin.location}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {checkin.status === "on-time" && (
                          <>
                            <CheckCircle2 className="w-4 h-4 text-success" />
                            <span className="text-xs text-success">On time</span>
                          </>
                        )}
                        {checkin.status === "late" && (
                          <>
                            <AlertTriangle className="w-4 h-4 text-warning" />
                            <span className="text-xs text-warning">Late ({checkin.time})</span>
                          </>
                        )}
                        {checkin.status === "missed" && (
                          <>
                            <XCircle className="w-4 h-4 text-destructive" />
                            <span className="text-xs text-destructive">Missed</span>
                          </>
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-4">No check-ins yet</p>
                )}
              </div>
            </div>
          </div>

          {/* Right column - Upcoming schedule */}
          <div className="space-y-4">
            <div className="bg-card rounded-xl border border-border p-5 shadow-card">
              <h3 className="font-semibold text-foreground mb-4">Upcoming Schedule</h3>
              {upcomingSchedule.length > 0 ? (
                <div className="space-y-3">
                  {upcomingSchedule.map((session: any) => (
                    <div key={session.id} className="p-3 rounded-lg border border-border hover:bg-muted/50 transition-colors cursor-pointer">
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <Calendar className="w-4 h-4 text-primary" />
                        {new Date(session.date).toLocaleDateString('en-ZA', { weekday: 'long', month: 'short', day: 'numeric' })}
                      </div>
                      <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                        <div className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {session.time}
                        </div>
                        <div className="flex items-center gap-1">
                          <MapPin className="w-3 h-3" />
                          {session.location}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8">
                  <Calendar className="w-10 h-10 text-muted-foreground/30 mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">No upcoming sessions</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
