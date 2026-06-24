import { useState, useEffect } from "react";
import { MainLayout } from "@/components/layout/MainLayout";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { UserPlus, Loader2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/contexts/AuthContext";
import { RoleGuard } from "@/components/ui/RoleGuard";
import { adminsAPI, authAPI } from "@/services/api";

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  location_admin: "Location Admin",
};

interface AdminRow {
  id: string;
  first_name?: string;
  last_name?: string;
  name?: string;
  email: string;
  role: string;
  is_active?: boolean;
  status?: string;
}

function displayName(a: AdminRow): string {
  if (a.name) return a.name;
  const full = `${a.first_name ?? ""} ${a.last_name ?? ""}`.trim();
  return full || a.email;
}

function isActive(a: AdminRow): boolean {
  if (typeof a.is_active === "boolean") return a.is_active;
  return (a.status ?? "active") === "active";
}

export default function UserManagement() {
  const { toast } = useToast();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const isLocationAdmin = user?.role === "location_admin";
  const canManage = isSuperAdmin || isLocationAdmin;
  // Super admins may invite location admins or coaches; location admins may
  // only invite coaches.
  const defaultInviteRole = isSuperAdmin ? "location_admin" : "coach";

  const [admins, setAdmins] = useState<AdminRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState(defaultInviteRole);
  const [inviting, setInviting] = useState(false);

  const loadAdmins = async () => {
    try {
      setLoading(true);
      const res = await adminsAPI.getAll();
      setAdmins(res.admins || []);
    } catch (err) {
      toast({
        title: "Failed to load users",
        description: "Could not load users. Please try again.",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (canManage) {
      loadAdmins();
    } else {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canManage]);

  const handleInvite = async () => {
    if (!inviteEmail.trim()) {
      toast({ title: "Email required", description: "Enter an email to invite.", variant: "destructive" });
      return;
    }
    try {
      setInviting(true);
      await authAPI.invite(inviteEmail.trim(), inviteRole);
      toast({ title: "Invite sent", description: `An invitation was sent to ${inviteEmail.trim()}.` });
      setDialogOpen(false);
      setInviteEmail("");
      setInviteRole(defaultInviteRole);
    } catch (err: any) {
      toast({
        title: "Invite failed",
        description: err?.message || "Could not send the invite. Please try again.",
        variant: "destructive",
      });
    } finally {
      setInviting(false);
    }
  };

  if (!canManage) {
    return (
      <MainLayout>
        <div className="space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Users</h1>
          </div>
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              You don't have permission to view this page.
            </CardContent>
          </Card>
        </div>
      </MainLayout>
    );
  }

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Users</h1>
            <p className="text-muted-foreground">Manage admins and invite new users to your organisation</p>
          </div>
          <RoleGuard allowedRoles={["super_admin", "location_admin"]}>
            <Button onClick={() => setDialogOpen(true)} className="gap-2">
              <UserPlus className="w-4 h-4" />
              Invite user
            </Button>
          </RoleGuard>
        </div>

        {/* Location filtering isn't wired yet — location admins see all org users for now. */}
        {isLocationAdmin && (
          <div className="rounded-md bg-muted px-4 py-2.5 text-sm text-muted-foreground">
            Location filtering coming soon
          </div>
        )}

        <Card>
          <CardContent className="p-0">
            {loading ? (
              <div className="flex items-center justify-center py-16 text-muted-foreground">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                Loading users...
              </div>
            ) : admins.length === 0 ? (
              <div className="py-12 text-center text-muted-foreground">No users yet</div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {admins.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell className="font-medium">{displayName(a)}</TableCell>
                      <TableCell className="text-muted-foreground">{a.email}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{ROLE_LABELS[a.role] || a.role}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={
                            isActive(a)
                              ? "bg-success/10 text-success border-success/20"
                              : "bg-muted text-muted-foreground"
                          }
                        >
                          {isActive(a) ? "Active" : "Inactive"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">—</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Invite dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Invite user</DialogTitle>
            <DialogDescription>
              Send an invitation email. The user sets their own name and password.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                placeholder="user@example.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                disabled={inviting}
              />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={inviteRole} onValueChange={setInviteRole} disabled={inviting}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {isSuperAdmin && <SelectItem value="location_admin">Location Admin</SelectItem>}
                  <SelectItem value="coach">Coach</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={inviting}>
              Cancel
            </Button>
            <Button onClick={handleInvite} disabled={inviting} className="gap-2">
              {inviting && <Loader2 className="w-4 h-4 animate-spin" />}
              Send invite
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </MainLayout>
  );
}
