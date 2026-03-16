import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MapPin, User, Calendar, Clock, FileText, Shield, Trash2, Loader2, Bell, Repeat, Pencil } from "lucide-react";
import { sessionsAPI } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

interface Session {
  id: number;
  date: string;
  coach: string;
  team: string;
  location: string;
  time: string;
  endTime?: string;
  type: string;
  status: string;
  notes?: string;
  recurrence_group_id?: string;
}

interface SessionDetailModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: Session | null;
  onDelete?: (sessionId: number, scope?: 'single' | 'future' | 'all') => Promise<void>;
  onEdit?: (session: Session) => void;
}

export function SessionDetailModal({ open, onOpenChange, session, onDelete, onEdit }: SessionDetailModalProps) {
  const { toast } = useToast();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteScope, setDeleteScope] = useState<'single' | 'future' | 'all'>('single');
  const [deleting, setDeleting] = useState(false);
  const [sendingReminder, setSendingReminder] = useState(false);

  // Reset deleteScope when viewing a different session
  useEffect(() => {
    setDeleteScope('single');
  }, [session?.id]);

  const handleSendReminder = async () => {
    if (!session) return;
    setSendingReminder(true);
    try {
      await sessionsAPI.sendReminder(session.id.toString());
      toast({ title: "Reminder sent", description: `WhatsApp reminder sent to ${session.coach}.` });
    } catch (err: any) {
      toast({ title: "Reminder failed", description: err.message || "Failed to send reminder.", variant: "destructive" });
    } finally {
      setSendingReminder(false);
    }
  };

  if (!session) return null;

  const handleDelete = async () => {
    if (!onDelete) return;
    setDeleting(true);
    try {
      await onDelete(session.id, session.recurrence_group_id ? deleteScope : 'single');
      setShowDeleteConfirm(false);
    } catch {
      // Error handling is done in the parent
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <span>Session Details</span>
              <Badge
                variant="outline"
                className={
                  session.type === "match"
                    ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
                    : "bg-emerald-500/10 text-emerald-600 border-emerald-500/30"
                }
              >
                {session.type === "match" ? "Match" : "Practice"}
              </Badge>
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* Team */}
            <div className="flex items-start gap-3">
              <Shield className="w-5 h-5 text-muted-foreground mt-0.5" />
              <div>
                <p className="text-sm text-muted-foreground">Team</p>
                <p className="font-medium text-foreground">{session.team}</p>
              </div>
            </div>

            {/* Coach */}
            <div className="flex items-start gap-3">
              <User className="w-5 h-5 text-muted-foreground mt-0.5" />
              <div>
                <p className="text-sm text-muted-foreground">Coach</p>
                <p className="font-medium text-foreground">{session.coach}</p>
              </div>
            </div>

            {/* Location */}
            <div className="flex items-start gap-3">
              <MapPin className="w-5 h-5 text-muted-foreground mt-0.5" />
              <div>
                <p className="text-sm text-muted-foreground">Location</p>
                <p className="font-medium text-foreground">{session.location}</p>
              </div>
            </div>

            {/* Date & Time */}
            <div className="flex items-start gap-3">
              <Calendar className="w-5 h-5 text-muted-foreground mt-0.5" />
              <div>
                <p className="text-sm text-muted-foreground">Date</p>
                <p className="font-medium text-foreground">{session.date}</p>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <Clock className="w-5 h-5 text-muted-foreground mt-0.5" />
              <div>
                <p className="text-sm text-muted-foreground">Time</p>
                <p className="font-medium text-foreground">
                  {session.time}{session.endTime ? ` - ${session.endTime}` : ""}
                </p>
              </div>
            </div>

            {/* Notes */}
            {session.notes && (
              <div className="flex items-start gap-3">
                <FileText className="w-5 h-5 text-muted-foreground mt-0.5" />
                <div>
                  <p className="text-sm text-muted-foreground">Notes</p>
                  <p className="font-medium text-foreground">{session.notes}</p>
                </div>
              </div>
            )}

            {/* Status */}
            <div className="pt-2 border-t border-border space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Status</span>
                <Badge variant="outline" className="capitalize">
                  {session.status}
                </Badge>
              </div>
              {session.recurrence_group_id && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Repeat className="w-4 h-4" />
                  <span>Part of a recurring series</span>
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="pt-2 border-t border-border space-y-2">
              {onEdit && (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full gap-2"
                  onClick={() => onEdit(session)}
                >
                  <Pencil className="w-4 h-4" />
                  Edit Session
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                className="w-full gap-2"
                onClick={handleSendReminder}
                disabled={sendingReminder}
              >
                {sendingReminder ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bell className="w-4 h-4" />}
                {sendingReminder ? "Sending..." : "Send Reminder"}
              </Button>
              {onDelete && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="w-full gap-2"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  <Trash2 className="w-4 h-4" />
                  Delete Session
                </Button>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Session?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete the session for {session.team} on {session.date} at {session.time}. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>

          {session.recurrence_group_id && (
            <div className="space-y-2 py-2">
              <p className="text-sm font-medium">This is a recurring session. Delete:</p>
              <div className="space-y-1">
                {(["single", "future", "all"] as const).map((scope) => (
                  <label key={scope} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="radio"
                      name="deleteScope"
                      checked={deleteScope === scope}
                      onChange={() => setDeleteScope(scope)}
                      className="rounded-full"
                    />
                    {scope === "single" && "Only this session"}
                    {scope === "future" && "This and all future sessions"}
                    {scope === "all" && "All sessions in this series"}
                  </label>
                ))}
              </div>
            </div>
          )}

          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {deleting ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
