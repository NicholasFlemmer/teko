import { useState, useEffect } from "react";
import { MainLayout } from "@/components/layout/MainLayout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Bell, Clock, CheckCircle2, MessageSquare, ClipboardCheck, Users, Plus, Trash2, Loader2 } from "lucide-react";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { remindersAPI } from "@/services/api";

interface ReminderConfig {
  id: string;
  type: "check-in" | "roll-call" | "feedback";
  timing: "10min" | "30min" | "1hr" | "post-session";
  enabled: boolean;
  description: string;
}

const reminderTypeConfig = {
  "check-in": {
    label: "Check-in Reminder",
    icon: CheckCircle2,
    color: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
  },
  "roll-call": {
    label: "Roll Call Reminder",
    icon: Users,
    color: "bg-blue-500/10 text-blue-600 border-blue-500/20",
  },
  "feedback": {
    label: "Feedback Request",
    icon: MessageSquare,
    color: "bg-amber-500/10 text-amber-600 border-amber-500/20",
  },
};

const timingLabels: Record<string, string> = {
  "10min": "10 minutes before",
  "30min": "30 minutes before",
  "1hr": "1 hour before",
  "post-session": "After session ends",
};

export default function Reminders() {
  const { toast } = useToast();
  const [reminders, setReminders] = useState<ReminderConfig[]>([]);
  const [isAddingNew, setIsAddingNew] = useState(false);
  const [newReminderType, setNewReminderType] = useState<ReminderConfig["type"]>("check-in");
  const [newReminderTiming, setNewReminderTiming] = useState<ReminderConfig["timing"]>("30min");

  // Loading states
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  // Fetch reminders on mount
  useEffect(() => {
    const fetchReminders = async () => {
      setLoading(true);
      try {
        const res = await remindersAPI.getAll();
        if (res.success && res.reminders) {
          setReminders(
            res.reminders.map((r: any) => ({
              id: String(r.id),
              type: r.type || "check-in",
              timing: r.timing || "30min",
              enabled: r.enabled ?? true,
              description: r.description || "",
            }))
          );
        }
      } catch (err: any) {
        toast({
          title: "Error loading reminders",
          description: err.message || "Failed to load reminders.",
          variant: "destructive",
        });
      } finally {
        setLoading(false);
      }
    };
    fetchReminders();
  }, []);

  const toggleReminder = async (id: string) => {
    const reminder = reminders.find((r) => r.id === id);
    if (!reminder) return;

    const newEnabled = !reminder.enabled;
    // Optimistic update
    setReminders(
      reminders.map((r) => (r.id === id ? { ...r, enabled: newEnabled } : r))
    );

    try {
      await remindersAPI.update(id, { enabled: newEnabled });
    } catch (err: any) {
      // Revert on failure
      setReminders(
        reminders.map((r) => (r.id === id ? { ...r, enabled: !newEnabled } : r))
      );
      toast({
        title: "Update failed",
        description: err.message || "Failed to update reminder.",
        variant: "destructive",
      });
    }
  };

  const deleteReminder = async (id: string) => {
    const prev = reminders;
    setReminders(reminders.filter((r) => r.id !== id));

    try {
      await remindersAPI.delete(id);
      toast({ title: "Reminder deleted" });
    } catch (err: any) {
      setReminders(prev);
      toast({
        title: "Delete failed",
        description: err.message || "Failed to delete reminder.",
        variant: "destructive",
      });
    }
  };

  const addReminder = async () => {
    const descriptions: Record<string, string> = {
      "check-in": "Remind coaches to check in before their session",
      "roll-call": "Prompt coaches to prepare for attendance",
      "feedback": "Request session feedback from coaches",
    };

    setCreating(true);
    try {
      const res = await remindersAPI.create({
        type: newReminderType,
        timing: newReminderTiming,
        enabled: true,
        description: descriptions[newReminderType],
      });

      if (res.success && res.reminder) {
        const newReminder: ReminderConfig = {
          id: String(res.reminder.id),
          type: res.reminder.type || newReminderType,
          timing: res.reminder.timing || newReminderTiming,
          enabled: res.reminder.enabled ?? true,
          description: res.reminder.description || descriptions[newReminderType],
        };
        setReminders([...reminders, newReminder]);
        toast({ title: "Reminder created" });
      }

      setIsAddingNew(false);
      setNewReminderType("check-in");
      setNewReminderTiming("30min");
    } catch (err: any) {
      toast({
        title: "Create failed",
        description: err.message || "Failed to create reminder.",
        variant: "destructive",
      });
    } finally {
      setCreating(false);
    }
  };

  const activeReminders = reminders.filter((r) => r.enabled).length;

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Coach Reminders</h1>
            <p className="text-muted-foreground">
              Set up automated reminders for coaches before and after sessions
            </p>
          </div>
          <Button onClick={() => setIsAddingNew(true)} className="gap-2">
            <Plus className="w-4 h-4" />
            Add Reminder
          </Button>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className="p-3 rounded-full bg-primary/10">
                  <Bell className="w-6 h-6 text-primary" />
                </div>
                <div>
                  <p className="text-2xl font-bold">{reminders.length}</p>
                  <p className="text-sm text-muted-foreground">Total Reminders</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className="p-3 rounded-full bg-emerald-500/10">
                  <CheckCircle2 className="w-6 h-6 text-emerald-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold">{activeReminders}</p>
                  <p className="text-sm text-muted-foreground">Active Reminders</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className="p-3 rounded-full bg-blue-500/10">
                  <Clock className="w-6 h-6 text-blue-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold">24/7</p>
                  <p className="text-sm text-muted-foreground">Automated Delivery</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Add New Reminder Form */}
        {isAddingNew && (
          <Card className="border-primary/50 bg-primary/5">
            <CardHeader>
              <CardTitle className="text-lg">Create New Reminder</CardTitle>
              <CardDescription>Configure when and what type of reminder to send</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Reminder Type</Label>
                  <Select
                    value={newReminderType}
                    onValueChange={(v) => setNewReminderType(v as ReminderConfig["type"])}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="check-in">Check-in Reminder</SelectItem>
                      <SelectItem value="roll-call">Roll Call Reminder</SelectItem>
                      <SelectItem value="feedback">Feedback Request</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Timing</Label>
                  <Select
                    value={newReminderTiming}
                    onValueChange={(v) => setNewReminderTiming(v as ReminderConfig["timing"])}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="10min">10 minutes before</SelectItem>
                      <SelectItem value="30min">30 minutes before</SelectItem>
                      <SelectItem value="1hr">1 hour before</SelectItem>
                      <SelectItem value="post-session">After session ends</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex gap-2 pt-2">
                <Button onClick={addReminder} disabled={creating}>
                  {creating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin mr-2" />
                      Creating...
                    </>
                  ) : (
                    "Create Reminder"
                  )}
                </Button>
                <Button variant="outline" onClick={() => setIsAddingNew(false)} disabled={creating}>
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Reminders List */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardCheck className="w-5 h-5" />
              Configured Reminders
            </CardTitle>
            <CardDescription>
              Manage automated notifications sent to coaches
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="space-y-4">
                {reminders.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <Bell className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>No reminders configured yet</p>
                    <p className="text-sm">Click "Add Reminder" to get started</p>
                  </div>
                ) : (
                  reminders.map((reminder) => {
                    const config = reminderTypeConfig[reminder.type] || reminderTypeConfig["check-in"];
                    const Icon = config.icon;

                    return (
                      <div
                        key={reminder.id}
                        className={`flex items-center justify-between p-4 rounded-lg border transition-all ${
                          reminder.enabled
                            ? "bg-card border-border"
                            : "bg-muted/50 border-muted opacity-60"
                        }`}
                      >
                        <div className="flex items-center gap-4">
                          <div className={`p-2 rounded-lg ${config.color}`}>
                            <Icon className="w-5 h-5" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{config.label}</span>
                              <Badge variant="secondary" className="text-xs">
                                {timingLabels[reminder.timing] || reminder.timing}
                              </Badge>
                            </div>
                            <p className="text-sm text-muted-foreground">
                              {reminder.description}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <Switch
                            checked={reminder.enabled}
                            onCheckedChange={() => toggleReminder(reminder.id)}
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            className="text-muted-foreground hover:text-destructive"
                            onClick={() => deleteReminder(reminder.id)}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* How It Works */}
        <Card>
          <CardHeader>
            <CardTitle>How Reminders Work</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="text-center space-y-2">
                <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mx-auto">
                  <span className="text-lg font-bold text-primary">1</span>
                </div>
                <h4 className="font-medium">Session Scheduled</h4>
                <p className="text-sm text-muted-foreground">
                  When a coaching session is created, reminders are automatically queued
                </p>
              </div>
              <div className="text-center space-y-2">
                <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mx-auto">
                  <span className="text-lg font-bold text-primary">2</span>
                </div>
                <h4 className="font-medium">Timed Delivery</h4>
                <p className="text-sm text-muted-foreground">
                  Notifications are sent at the configured time before or after sessions
                </p>
              </div>
              <div className="text-center space-y-2">
                <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mx-auto">
                  <span className="text-lg font-bold text-primary">3</span>
                </div>
                <h4 className="font-medium">Coach Action</h4>
                <p className="text-sm text-muted-foreground">
                  Coaches receive prompts to check in, take attendance, or provide feedback
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </MainLayout>
  );
}
