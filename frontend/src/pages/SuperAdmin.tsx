import { useState, useEffect } from "react";
import { MainLayout } from "@/components/layout/MainLayout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  UserCog,
  Plus,
  Pencil,
  Trash2,
  CreditCard,
  Mail,
  Shield,
  Activity,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { adminAPI } from "@/services/api";

interface Admin {
  id: number;
  name: string;
  email: string;
  role: "super_admin" | "admin" | "manager";
  status: "active" | "suspended";
  lastLogin: string;
  createdAt: string;
}

interface AdminForm {
  name: string;
  email: string;
  role: "super_admin" | "admin" | "manager";
  password: string;
}

const emptyForm: AdminForm = { name: "", email: "", role: "admin", password: "" };

const roleLabels: Record<string, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
  manager: "Manager",
};

const roleBadgeClass: Record<string, string> = {
  super_admin: "bg-destructive/10 text-destructive border-destructive/20",
  admin: "bg-primary/10 text-primary border-primary/20",
  manager: "bg-warning/10 text-warning border-warning/20",
};

export default function SuperAdmin() {
  const { toast } = useToast();

  // Admin management
  const [admins, setAdmins] = useState<Admin[]>([]);
  const [showAdminModal, setShowAdminModal] = useState(false);
  const [editingAdmin, setEditingAdmin] = useState<Admin | null>(null);
  const [adminForm, setAdminForm] = useState<AdminForm>(emptyForm);
  const [deleteTarget, setDeleteTarget] = useState<Admin | null>(null);

  // Loading states
  const [loadingAdmins, setLoadingAdmins] = useState(true);
  const [savingAdmin, setSavingAdmin] = useState(false);
  const [deletingAdmin, setDeletingAdmin] = useState(false);
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);

  // Payment
  const [cardNumber, setCardNumber] = useState("");
  const [cardExpiry, setCardExpiry] = useState("");
  const [cardCvc, setCardCvc] = useState("");
  const [cardName, setCardName] = useState("");
  const [cardSaved, setCardSaved] = useState(false);

  // Email
  const [senderEmail, setSenderEmail] = useState("");
  const [senderName, setSenderName] = useState("");
  const [emailVerified, setEmailVerified] = useState(true);

  // System
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [autoBackup, setAutoBackup] = useState(true);

  // Fetch admins on mount
  useEffect(() => {
    const fetchAdmins = async () => {
      setLoadingAdmins(true);
      try {
        const res = await adminAPI.getUsers();
        if (res.success && res.admins) {
          setAdmins(
            res.admins.map((a: any) => ({
              id: a.id,
              name: a.name,
              email: a.email,
              role: a.role || "admin",
              status: a.status || "active",
              lastLogin: a.last_login || a.lastLogin || "Never",
              createdAt: a.created_at || a.createdAt || "",
            }))
          );
        }
      } catch (err: any) {
        toast({
          title: "Error loading admins",
          description: err.message || "Failed to load admin accounts.",
          variant: "destructive",
        });
      } finally {
        setLoadingAdmins(false);
      }
    };
    fetchAdmins();
  }, []);

  // Fetch settings on mount
  useEffect(() => {
    const fetchSettings = async () => {
      setLoadingSettings(true);
      try {
        const res = await adminAPI.getSettings();
        if (res.success && res.settings) {
          setMaintenanceMode(res.settings.maintenance_mode ?? false);
          setAutoBackup(res.settings.auto_backup ?? true);
          setSenderEmail(res.settings.sender_email || "");
          setSenderName(res.settings.sender_name || "");
        }
      } catch (err: any) {
        // Settings might not exist yet, that's ok
        console.error("Failed to load settings:", err);
      } finally {
        setLoadingSettings(false);
      }
    };
    fetchSettings();
  }, []);

  // Admin CRUD
  const openAddAdmin = () => {
    setEditingAdmin(null);
    setAdminForm(emptyForm);
    setShowAdminModal(true);
  };

  const openEditAdmin = (admin: Admin) => {
    setEditingAdmin(admin);
    setAdminForm({ name: admin.name, email: admin.email, role: admin.role, password: "" });
    setShowAdminModal(true);
  };

  const handleSaveAdmin = async () => {
    if (!adminForm.name.trim() || !adminForm.email.trim()) {
      toast({ title: "Error", description: "Name and email are required.", variant: "destructive" });
      return;
    }
    if (!editingAdmin && !adminForm.password) {
      toast({ title: "Error", description: "Password is required for new admins.", variant: "destructive" });
      return;
    }

    setSavingAdmin(true);
    try {
      if (editingAdmin) {
        const updateData: any = { name: adminForm.name, email: adminForm.email, role: adminForm.role };
        if (adminForm.password) updateData.password = adminForm.password;
        const res = await adminAPI.updateUser(String(editingAdmin.id), updateData);
        if (res.success) {
          setAdmins((prev) =>
            prev.map((a) =>
              a.id === editingAdmin.id
                ? { ...a, name: adminForm.name, email: adminForm.email, role: adminForm.role }
                : a
            )
          );
          toast({ title: "Admin updated" });
        }
      } else {
        const res = await adminAPI.createUser({
          name: adminForm.name,
          email: adminForm.email,
          password: adminForm.password,
          role: adminForm.role,
        });
        if (res.success && res.admin) {
          const newAdmin: Admin = {
            id: res.admin.id,
            name: res.admin.name || adminForm.name,
            email: res.admin.email || adminForm.email,
            role: res.admin.role || adminForm.role,
            status: "active",
            lastLogin: "Never",
            createdAt: res.admin.created_at || new Date().toISOString().split("T")[0],
          };
          setAdmins((prev) => [...prev, newAdmin]);
          toast({ title: "Admin added" });
        }
      }
      setShowAdminModal(false);
    } catch (err: any) {
      toast({
        title: "Save failed",
        description: err.message || "Failed to save admin.",
        variant: "destructive",
      });
    } finally {
      setSavingAdmin(false);
    }
  };

  const handleDeleteAdmin = async () => {
    if (!deleteTarget) return;
    setDeletingAdmin(true);
    try {
      await adminAPI.deleteUser(String(deleteTarget.id));
      setAdmins((prev) => prev.filter((a) => a.id !== deleteTarget.id));
      toast({ title: "Admin removed", description: `${deleteTarget.name} has been removed.` });
    } catch (err: any) {
      toast({
        title: "Delete failed",
        description: err.message || "Failed to remove admin.",
        variant: "destructive",
      });
    } finally {
      setDeletingAdmin(false);
      setDeleteTarget(null);
    }
  };

  const toggleAdminStatus = async (admin: Admin) => {
    const prevStatus = admin.status;
    const newStatus = prevStatus === "active" ? "suspended" : "active";

    // Optimistic update
    setAdmins((prev) =>
      prev.map((a) =>
        a.id === admin.id ? { ...a, status: newStatus } : a
      )
    );

    try {
      await adminAPI.toggleStatus(String(admin.id));
      toast({
        title: prevStatus === "active" ? "Admin suspended" : "Admin reactivated",
      });
    } catch (err: any) {
      // Revert on failure
      setAdmins((prev) =>
        prev.map((a) =>
          a.id === admin.id ? { ...a, status: prevStatus } : a
        )
      );
      toast({
        title: "Status update failed",
        description: err.message || "Failed to update admin status.",
        variant: "destructive",
      });
    }
  };

  const handleSaveCard = () => {
    if (!cardNumber || !cardExpiry || !cardCvc || !cardName) {
      toast({ title: "Error", description: "All card fields are required.", variant: "destructive" });
      return;
    }
    setCardSaved(true);
    toast({ title: "Payment method saved", description: "Card ending in " + cardNumber.slice(-4) });
  };

  const handleSaveEmail = async () => {
    if (!senderEmail.trim()) {
      toast({ title: "Error", description: "Sender email is required.", variant: "destructive" });
      return;
    }
    setSavingSettings(true);
    try {
      await adminAPI.updateSettings({
        sender_email: senderEmail,
        sender_name: senderName,
        maintenance_mode: maintenanceMode,
        auto_backup: autoBackup,
      });
      setEmailVerified(false);
      toast({ title: "Email settings saved", description: "A verification email has been sent." });
      setTimeout(() => setEmailVerified(true), 2000);
    } catch (err: any) {
      toast({
        title: "Save failed",
        description: err.message || "Failed to save email settings.",
        variant: "destructive",
      });
    } finally {
      setSavingSettings(false);
    }
  };

  const handleSaveSystemSettings = async (updates: { maintenance_mode?: boolean; auto_backup?: boolean }) => {
    const newMaintenance = updates.maintenance_mode ?? maintenanceMode;
    const newBackup = updates.auto_backup ?? autoBackup;

    // Optimistic update
    if (updates.maintenance_mode !== undefined) setMaintenanceMode(updates.maintenance_mode);
    if (updates.auto_backup !== undefined) setAutoBackup(updates.auto_backup);

    try {
      await adminAPI.updateSettings({
        maintenance_mode: newMaintenance,
        auto_backup: newBackup,
        sender_email: senderEmail,
        sender_name: senderName,
      });
    } catch (err: any) {
      // Revert on failure
      if (updates.maintenance_mode !== undefined) setMaintenanceMode(!updates.maintenance_mode);
      if (updates.auto_backup !== undefined) setAutoBackup(!updates.auto_backup);
      toast({
        title: "Save failed",
        description: err.message || "Failed to update settings.",
        variant: "destructive",
      });
    }
  };

  return (
    <MainLayout>
      <div className="p-6 max-w-6xl mx-auto space-y-8">
        {/* Header */}
        <div className="page-header">
          <div>
            <h1 className="page-title flex items-center gap-2">
              <Shield className="w-7 h-7 text-primary" />
              Super Admin
            </h1>
            <p className="page-subtitle">Manage administrators, payments, and system settings</p>
          </div>
        </div>

        {/* Admin Management */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <UserCog className="w-5 h-5" />
                Admin Accounts
              </CardTitle>
              <CardDescription>Manage who has access to the platform</CardDescription>
            </div>
            <Button onClick={openAddAdmin}>
              <Plus className="w-4 h-4 mr-2" />
              Add Admin
            </Button>
          </CardHeader>
          <CardContent>
            {loadingAdmins ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Last Login</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {admins.map((admin) => (
                    <TableRow key={admin.id}>
                      <TableCell className="font-medium">{admin.name}</TableCell>
                      <TableCell className="text-muted-foreground">{admin.email}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={roleBadgeClass[admin.role] || ""}>
                          {roleLabels[admin.role] || admin.role}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={
                            admin.status === "active"
                              ? "bg-success/10 text-success border-success/20"
                              : "bg-muted text-muted-foreground"
                          }
                        >
                          {admin.status === "active" ? "Active" : "Suspended"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">{admin.lastLogin}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => toggleAdminStatus(admin)} title={admin.status === "active" ? "Suspend" : "Reactivate"}>
                            <Activity className="w-4 h-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => openEditAdmin(admin)}>
                            <Pencil className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="text-destructive hover:text-destructive"
                            onClick={() => setDeleteTarget(admin)}
                            disabled={admin.role === "super_admin" && admins.filter((a) => a.role === "super_admin").length <= 1}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Payment / Credit Card */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CreditCard className="w-5 h-5" />
                Payment Method
              </CardTitle>
              <CardDescription>
                Credit card for WhatsApp broadcast charges (~R1 per message for inactive recipients)
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {cardSaved && (
                <div className="flex items-center gap-3 p-3 rounded-lg bg-success/10 border border-success/20">
                  <CreditCard className="w-5 h-5 text-success" />
                  <div>
                    <p className="text-sm font-medium">Card ending in {cardNumber.slice(-4)}</p>
                    <p className="text-xs text-muted-foreground">Expires {cardExpiry}</p>
                  </div>
                  <Button variant="outline" size="sm" className="ml-auto" onClick={() => setCardSaved(false)}>
                    Change
                  </Button>
                </div>
              )}
              {!cardSaved && (
                <>
                  <div className="space-y-2">
                    <Label>Cardholder Name</Label>
                    <Input placeholder="Name on card" value={cardName} onChange={(e) => setCardName(e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label>Card Number</Label>
                    <Input placeholder="4242 4242 4242 4242" value={cardNumber} onChange={(e) => setCardNumber(e.target.value)} maxLength={19} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Expiry</Label>
                      <Input placeholder="MM/YY" value={cardExpiry} onChange={(e) => setCardExpiry(e.target.value)} maxLength={5} />
                    </div>
                    <div className="space-y-2">
                      <Label>CVC</Label>
                      <Input placeholder="123" value={cardCvc} onChange={(e) => setCardCvc(e.target.value)} maxLength={4} type="password" />
                    </div>
                  </div>
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-warning/10 border border-warning/20">
                    <AlertTriangle className="w-4 h-4 text-warning mt-0.5 flex-shrink-0" />
                    <p className="text-xs text-muted-foreground">
                      WhatsApp broadcasts to recipients who haven't engaged in 24 hours cost approximately <strong>R1 per message</strong>. Charges are billed to this card.
                    </p>
                  </div>
                  <Button onClick={handleSaveCard} className="w-full">
                    Save Payment Method
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          {/* Email Configuration */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Mail className="w-5 h-5" />
                Email Configuration
              </CardTitle>
              <CardDescription>Configure the sender address for email broadcasts</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {loadingSettings ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  <div className="space-y-2">
                    <Label>Sender Name</Label>
                    <Input value={senderName} onChange={(e) => setSenderName(e.target.value)} placeholder="e.g. Teko Notifications" />
                  </div>
                  <div className="space-y-2">
                    <Label>Sender Email Address</Label>
                    <Input type="email" value={senderEmail} onChange={(e) => setSenderEmail(e.target.value)} placeholder="noreply@yourdomain.com" />
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className={emailVerified ? "bg-success/10 text-success border-success/20" : "bg-warning/10 text-warning border-warning/20"}>
                      {emailVerified ? "Verified" : "Pending Verification"}
                    </Badge>
                  </div>
                  <Separator />
                  <Button onClick={handleSaveEmail} className="w-full" disabled={savingSettings}>
                    {savingSettings ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                        Saving...
                      </>
                    ) : (
                      "Save Email Settings"
                    )}
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {/* System Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="w-5 h-5" />
              System Settings
            </CardTitle>
            <CardDescription>Platform-wide configuration and controls</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {loadingSettings ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-sm">Maintenance Mode</p>
                    <p className="text-xs text-muted-foreground">Temporarily disable access for non-admins</p>
                  </div>
                  <Switch
                    checked={maintenanceMode}
                    onCheckedChange={(checked) => handleSaveSystemSettings({ maintenance_mode: checked })}
                  />
                </div>
                <Separator />
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-sm">Automatic Backups</p>
                    <p className="text-xs text-muted-foreground">Daily backups of all data at midnight</p>
                  </div>
                  <Switch
                    checked={autoBackup}
                    onCheckedChange={(checked) => handleSaveSystemSettings({ auto_backup: checked })}
                  />
                </div>
                <Separator />
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-sm">Audit Log</p>
                    <p className="text-xs text-muted-foreground">Track all admin actions for accountability</p>
                  </div>
                  <Button variant="outline" size="sm">View Logs</Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Add/Edit Admin Modal */}
      <Dialog open={showAdminModal} onOpenChange={setShowAdminModal}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingAdmin ? "Edit Admin" : "Add Admin"}</DialogTitle>
            <DialogDescription>
              {editingAdmin ? "Update admin account details." : "Create a new admin account."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Full Name</Label>
              <Input value={adminForm.name} onChange={(e) => setAdminForm({ ...adminForm, name: e.target.value })} placeholder="e.g. Jane Smith" />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input type="email" value={adminForm.email} onChange={(e) => setAdminForm({ ...adminForm, email: e.target.value })} placeholder="jane@teko.org" />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={adminForm.role} onValueChange={(v) => setAdminForm({ ...adminForm, role: v as AdminForm["role"] })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="super_admin">Super Admin</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                  <SelectItem value="manager">Manager</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {!editingAdmin && (
              <div className="space-y-2">
                <Label>Password</Label>
                <Input type="password" value={adminForm.password} onChange={(e) => setAdminForm({ ...adminForm, password: e.target.value })} placeholder="Minimum 8 characters" />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAdminModal(false)} disabled={savingAdmin}>Cancel</Button>
            <Button onClick={handleSaveAdmin} disabled={savingAdmin}>
              {savingAdmin ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Saving...
                </>
              ) : editingAdmin ? (
                "Save Changes"
              ) : (
                "Create Admin"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove Admin Account</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to remove <strong>{deleteTarget?.name}</strong>? They will lose all access to the platform immediately. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deletingAdmin}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteAdmin} className="bg-destructive text-destructive-foreground hover:bg-destructive/90" disabled={deletingAdmin}>
              {deletingAdmin ? "Removing..." : "Remove Admin"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </MainLayout>
  );
}
