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
import { MapPin, User, Calendar, Clock, FileText, Shield, Trash2, Loader2, Bell, Repeat, Pencil, XCircle, CheckCircle2, Timer } from "lucide-react";
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
  check_in_time?: any;
  location_verified?: boolean;
  distance?: number;
  completed_at?: any;
  cancelled_at?: string;
  cancellation_reason?: string;
  coach_check_ins?: Record<string, { check_in_time: any; location_verified: boolean; distance?: number }>;
}

interface SessionDetailModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: Session | null;
  onDelete?: (sessionId: number, scope?: 'single' | 'future' | 'all') => Promise<void>;
  onEdit?: (session: Session) => void;
  onStatusChange?: () => void;
}

function formatTimestamp(ts: any): string {
  if (!ts) return '-';
  // Firestore timestamps have _seconds or seconds property
  const seconds = ts._seconds ?? ts.seconds;
  if (seconds) return new Date(seconds * 1000).toLocaleString();
  // ISO string or Date
  const d = new Date(ts);
  return isNaN(d.getTime()) ? '-' : d.toLocaleString();
}

function formatDuration(startTs: any, endTs: any): string | null {
  if (!startTs || !endTs) return null;
  const getMs = (ts: any) => {
    const seconds = ts._seconds ?? ts.seconds;
    return seconds ? seconds * 1000 : new Date(ts).getTime();
  };
  const ms = getMs(endTs) - getMs(startTs);
  if (isNaN(ms) || ms < 0) return null;
  const mins = Math.round(ms / 60000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

const statusBadgeClass: Record<string, string> = {
  scheduled: '',
  reminded: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  checked_in: 'bg-green-500/10 text-green-600 border-green-500/30',
  completed: 'bg-green-500/10 text-green-600 border-green-500/30',
  missed: 'bg-red-500/10 text-red-600 border-red-500/30',
  cancelled: 'bg-orange-500/10 text-orange-600 border-orange-500/30',
};

export function SessionDetailModal({ open, onOpenChange, session, onDelete, onEdit, onStatusChange }: SessionDetailModalProps) {
  const { toast } = useToast();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [deleteScope, setDeleteScope] = useState<'single' | 'future' | 'all'>('single');
  const [deleting, setDeleting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [sendingReminder, setSendingReminder] = useState(false);
  const [cancelReason, setCancelReason] = useState('');

  // Reset state when viewing a different session
  useEffect(() => {
    setDeleteScope('single');
    setCancelReason('');
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

  const handleCancel = async () => {
    if (!session) return;
    setCancelling(true);
    try {
      await sessionsAPI.cancel(session.id.toString(), cancelReason);
      toast({ title: "Session cancelled", description: `Session on ${session.date} has been cancelled.` });
      setShowCancelConfirm(false);
      onStatusChange?.();
      onOpenChange(false);
    } catch (err: any) {
      toast({ title: "Cancel failed", description: err.message || "Failed to cancel session.", variant: "destructive" });
    } finally {
      setCancelling(false);
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

  const canCancel = !['completed', 'cancelled'].includes(session.status);
  const showCheckInDetails = ['checked_in', 'completed', 'missed'].includes(session.status);
  const duration = formatDuration(session.check_in_time, session.completed_at);

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
                <Badge variant="outline" className={`capitalize ${statusBadgeClass[session.status] || ''}`}>
                  {session.status.replace('_', ' ')}
                </Badge>
              </div>
              {session.recurrence_group_id && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Repeat className="w-4 h-4" />
                  <span>Part of a recurring series</span>
                </div>
              )}
              {session.status === 'cancelled' && session.cancellation_reason && (
                <p className="text-sm text-muted-foreground">Reason: {session.cancellation_reason}</p>
              )}
            </div>

            {/* Check-in Details */}
            {showCheckInDetails && (
              <div className="pt-2 border-t border-border space-y-2">
                <p className="text-sm font-medium text-foreground">Check-in Details</p>
                {session.check_in_time && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Checked in</span>
                    <span>{formatTimestamp(session.check_in_time)}</span>
                  </div>
                )}
                {session.completed_at && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Completed</span>
                    <span>{formatTimestamp(session.completed_at)}</span>
                  </div>
                )}
                {duration && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground flex items-center gap-1"><Timer className="w-3.5 h-3.5" />Duration</span>
                    <span>{duration}</span>
                  </div>
                )}
                {session.distance != null && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Distance from venue</span>
                    <span>{session.distance < 1000 ? `${Math.round(session.distance)}m` : `${(session.distance / 1000).toFixed(1)}km`}</span>
                  </div>
                )}
                {session.location_verified != null && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Location verified</span>
                    {session.location_verified
                      ? <CheckCircle2 className="w-4 h-4 text-green-500" />
                      : <XCircle className="w-4 h-4 text-red-500" />}
                  </div>
                )}
              </div>
            )}

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
              {canCancel && (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full gap-2 text-orange-600 border-orange-300 hover:bg-orange-50"
                  onClick={() => setShowCancelConfirm(true)}
                >
                  <XCircle className="w-4 h-4" />
                  Cancel Session
                </Button>
              )}
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

      {/* Cancel Confirmation */}
      <AlertDialog open={showCancelConfirm} onOpenChange={setShowCancelConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel Session?</AlertDialogTitle>
            <AlertDialogDescription>
              This will mark the session for {session.team} on {session.date} as cancelled.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="py-2">
            <label className="text-sm font-medium">Reason (optional)</label>
            <input
              type="text"
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              placeholder="e.g. School has no water"
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={cancelling}>Back</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleCancel}
              disabled={cancelling}
              className="bg-orange-600 text-white hover:bg-orange-700"
            >
              {cancelling && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {cancelling ? "Cancelling..." : "Cancel Session"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete Confirmation */}
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
