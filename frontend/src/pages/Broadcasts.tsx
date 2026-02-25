import { useState, useEffect, useMemo } from "react";
import { Send, MessageSquare, Mail, Users, ChevronDown, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { MainLayout } from "@/components/layout/MainLayout";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useToast } from "@/hooks/use-toast";
import { broadcastsAPI, coachesAPI } from "@/services/api";

const COST_PER_MESSAGE = 1; // R1 per WhatsApp message outside 24h window

interface Recipient {
  id: number;
  name: string;
  phone: string;
  email: string;
  lastEngaged: string; // ISO date
}

export default function Broadcasts() {
  const { toast } = useToast();
  const [channel, setChannel] = useState<"whatsapp" | "email">("whatsapp");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [selectedRecipients, setSelectedRecipients] = useState<number[]>([]);
  const [allSelected, setAllSelected] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // API state
  const [recipients, setRecipients] = useState<Recipient[]>([]);
  const [broadcasts, setBroadcasts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  // Fetch recipients (coaches) and broadcast history on mount
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [coachesRes, broadcastsRes] = await Promise.all([
          coachesAPI.getAll(),
          broadcastsAPI.getAll(),
        ]);

        if (coachesRes.success && coachesRes.coaches) {
          setRecipients(
            coachesRes.coaches.map((c: any) => ({
              id: c.id,
              name: c.name,
              phone: c.phone_number || c.phone || "",
              email: c.email || "",
              lastEngaged: c.last_engaged || c.created_at || new Date().toISOString(),
            }))
          );
        }

        if (broadcastsRes.success && broadcastsRes.broadcasts) {
          setBroadcasts(broadcastsRes.broadcasts);
        }
      } catch (err: any) {
        toast({
          title: "Error loading data",
          description: err.message || "Failed to load broadcasts and recipients.",
          variant: "destructive",
        });
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const activeRecipients = allSelected ? recipients : recipients.filter(r => selectedRecipients.includes(r.id));

  const costBreakdown = useMemo(() => {
    if (channel !== "whatsapp") return { billable: 0, free: activeRecipients.length, total: 0 };
    const now = Date.now();
    const twentyFourHours = 24 * 60 * 60 * 1000;
    let billable = 0;
    let free = 0;
    activeRecipients.forEach(r => {
      if (now - new Date(r.lastEngaged).getTime() > twentyFourHours) {
        billable++;
      } else {
        free++;
      }
    });
    return { billable, free, total: billable * COST_PER_MESSAGE };
  }, [activeRecipients, channel]);

  const toggleRecipient = (id: number) => {
    setAllSelected(false);
    setSelectedRecipients(prev =>
      prev.includes(id) ? prev.filter(r => r !== id) : [...prev, id]
    );
  };

  const handleSelectAll = () => {
    setAllSelected(true);
    setSelectedRecipients([]);
  };

  const removeRecipient = (id: number) => {
    if (allSelected) {
      setAllSelected(false);
      setSelectedRecipients(recipients.filter(r => r.id !== id).map(r => r.id));
    } else {
      setSelectedRecipients(prev => prev.filter(r => r !== id));
    }
  };

  const canSend = (subject.trim() || channel === "whatsapp") && message.trim() && activeRecipients.length > 0 && !sending;

  const handleSend = async () => {
    setSending(true);
    try {
      await broadcastsAPI.send({
        channel,
        subject,
        message,
        recipient_ids: activeRecipients.map(r => r.id),
      });

      toast({ title: "Broadcast sent", description: `Message sent to ${activeRecipients.length} recipient${activeRecipients.length !== 1 ? "s" : ""}.` });

      setSubject("");
      setMessage("");
      setSelectedRecipients([]);
      setAllSelected(false);
      setConfirmOpen(false);

      // Refresh broadcast history
      try {
        const res = await broadcastsAPI.getAll();
        if (res.success && res.broadcasts) {
          setBroadcasts(res.broadcasts);
        }
      } catch {
        // silently fail on refresh
      }
    } catch (err: any) {
      toast({
        title: "Send failed",
        description: err.message || "Failed to send broadcast.",
        variant: "destructive",
      });
    } finally {
      setSending(false);
      setConfirmOpen(false);
    }
  };

  return (
    <MainLayout>
      <div className="space-y-6">
        <div className="page-header">
          <div>
            <h1 className="page-title">Broadcasts</h1>
            <p className="page-subtitle">Send announcements to coaches via WhatsApp or Email</p>
          </div>
        </div>

        {/* Compose */}
        <div className="bg-card rounded-xl border border-border p-6 shadow-card space-y-5">
          <h2 className="text-lg font-semibold text-foreground">New Broadcast</h2>

          {/* Channel toggle */}
          <div className="space-y-2">
            <Label>Channel</Label>
            <div className="flex gap-2">
              <Button
                variant={channel === "whatsapp" ? "default" : "outline"}
                size="sm"
                onClick={() => setChannel("whatsapp")}
                className="gap-2"
              >
                <MessageSquare className="w-4 h-4" />
                WhatsApp
              </Button>
              <Button
                variant={channel === "email" ? "default" : "outline"}
                size="sm"
                onClick={() => setChannel("email")}
                className="gap-2"
              >
                <Mail className="w-4 h-4" />
                Email
              </Button>
            </div>
          </div>

          {/* Recipients */}
          <div className="space-y-2">
            <Label>Recipients</Label>
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading coaches...
              </div>
            ) : (
              <>
                <div className="flex flex-wrap gap-2 mb-2">
                  {allSelected && (
                    <Badge variant="secondary" className="gap-1 pr-1">
                      All Coaches ({recipients.length})
                      <button onClick={() => { setAllSelected(false); setSelectedRecipients([]); }} className="ml-1 rounded-full hover:bg-muted p-0.5">
                        <X className="w-3 h-3" />
                      </button>
                    </Badge>
                  )}
                  {!allSelected && selectedRecipients.map(id => {
                    const r = recipients.find(r => r.id === id);
                    if (!r) return null;
                    return (
                      <Badge key={id} variant="secondary" className="gap-1 pr-1">
                        {r.name}
                        <button onClick={() => removeRecipient(id)} className="ml-1 rounded-full hover:bg-muted p-0.5">
                          <X className="w-3 h-3" />
                        </button>
                      </Badge>
                    );
                  })}
                </div>
                <Select
                  value=""
                  onValueChange={(val) => {
                    if (val === "all") handleSelectAll();
                    else toggleRecipient(Number(val));
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select recipients..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">
                      <span className="flex items-center gap-2">
                        <Users className="w-4 h-4" /> Select All Coaches
                      </span>
                    </SelectItem>
                    {recipients.map(r => (
                      <SelectItem key={r.id} value={String(r.id)}>
                        <span className="flex items-center gap-2">
                          {r.name}
                          {(allSelected || selectedRecipients.includes(r.id)) && (
                            <Badge variant="outline" className="text-xs ml-1">selected</Badge>
                          )}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            )}
          </div>

          {/* Subject */}
          <div className="space-y-2">
            <Label htmlFor="subject">Subject {channel === "whatsapp" && <span className="text-muted-foreground text-xs">(optional for WhatsApp)</span>}</Label>
            <Input
              id="subject"
              placeholder="Enter broadcast subject..."
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </div>

          {/* Message */}
          <div className="space-y-2">
            <Label htmlFor="message">Message</Label>
            <Textarea
              id="message"
              placeholder="Type your message here..."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={5}
            />
          </div>

          {/* Cost estimate for WhatsApp */}
          {channel === "whatsapp" && activeRecipients.length > 0 && (
            <div className="rounded-lg border border-border bg-muted/50 p-4 space-y-2">
              <h3 className="text-sm font-semibold text-foreground">WhatsApp Cost Estimate</h3>
              <p className="text-xs text-muted-foreground">
                Meta charges ~R1 per message for recipients who haven't engaged in the past 24 hours.
              </p>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-muted-foreground text-xs">Free (active)</p>
                  <p className="font-semibold text-foreground">{costBreakdown.free} recipient{costBreakdown.free !== 1 ? "s" : ""}</p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs">Billable (inactive)</p>
                  <p className="font-semibold text-foreground">{costBreakdown.billable} recipient{costBreakdown.billable !== 1 ? "s" : ""}</p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs">Est. Cost</p>
                  <p className="font-semibold text-foreground">R{costBreakdown.total.toFixed(2)}</p>
                </div>
              </div>
            </div>
          )}

          <Button onClick={() => setConfirmOpen(true)} disabled={!canSend} className="gap-2">
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Send Broadcast
          </Button>
        </div>

        {/* Previous broadcasts */}
        <div>
          <h2 className="text-lg font-semibold text-foreground mb-4">Previous Broadcasts</h2>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : broadcasts.length === 0 ? (
            <div className="text-center py-12">
              <MessageSquare className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
              <p className="text-muted-foreground">No broadcasts sent yet</p>
            </div>
          ) : (
            <div className="space-y-3">
              {broadcasts.map((b) => (
                <div key={b.id} className="bg-card rounded-xl border border-border p-4 shadow-card">
                  <div className="flex items-start gap-3">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 ${b.channel === "whatsapp" ? "bg-primary/10" : "bg-accent"}`}>
                      {b.channel === "whatsapp" ? <MessageSquare className="w-5 h-5 text-primary" /> : <Mail className="w-5 h-5 text-accent-foreground" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-foreground">{b.subject || "(No subject)"}</p>
                      <p className="text-sm text-muted-foreground mt-0.5">{b.message}</p>
                      <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                        <span>{b.recipient_count ?? b.recipients ?? 0} recipients</span>
                        <span>•</span>
                        <span>{b.created_at ? new Date(b.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : b.date}</span>
                        {b.channel === "whatsapp" && (b.cost ?? 0) > 0 && (
                          <>
                            <span>•</span>
                            <span>R{Number(b.cost).toFixed(2)}</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-xs capitalize">{b.channel}</Badge>
                      <Badge variant="secondary" className="text-xs capitalize bg-primary/10 text-primary">{b.status || "sent"}</Badge>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Confirm send dialog */}
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Send Broadcast?</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <span className="block">
                You're about to send a {channel === "whatsapp" ? "WhatsApp" : "Email"} broadcast to{" "}
                <strong>{activeRecipients.length} recipient{activeRecipients.length !== 1 ? "s" : ""}</strong>.
              </span>
              {channel === "whatsapp" && costBreakdown.total > 0 && (
                <span className="block font-medium">
                  Estimated WhatsApp cost: R{costBreakdown.total.toFixed(2)} ({costBreakdown.billable} billable message{costBreakdown.billable !== 1 ? "s" : ""})
                </span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={sending}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleSend} disabled={sending}>
              {sending ? "Sending..." : "Send Now"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </MainLayout>
  );
}
