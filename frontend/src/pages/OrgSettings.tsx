import { useState, useEffect } from "react";
import { MainLayout } from "@/components/layout/MainLayout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Building2, Loader2, Save, ShieldAlert, AlertTriangle } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/contexts/AuthContext";
import { useRefreshTerminology } from "@/contexts/TerminologyContext";
import { organisationsAPI } from "@/services/api";
import {
  DEFAULT_TERMINOLOGY,
  getDefaultTerminology,
  type Organisation,
  type OrganisationType,
  type Terminology,
} from "@/types/Organisation";

const ORG_TYPE_LABELS: Record<OrganisationType, string> = {
  sports: "Sports",
  ngo: "NGO",
  events: "Events",
  corporate: "Corporate",
};

/** Bug 2 fix: the badge previously read "Configured" as soon as ANY one
 * of the three safeguarding fields was set (e.g. a lead name alone).
 * "Configured" now requires ALL three to hold a real value -- lead name
 * and lead email both non-blank after trimming, and works_with_minors an
 * actual true/false decision (not null/unset). Anything short of that
 * reads as "Not configured", including a partial record. Exported so it
 * can be unit-tested without rendering the page. */
export function isSafeguardingFullyConfigured(
  org:
    | Pick<Organisation, "safeguarding_lead_name" | "safeguarding_lead_email" | "works_with_minors">
    | null
    | undefined
): boolean {
  const hasLeadName = Boolean(org?.safeguarding_lead_name && org.safeguarding_lead_name.trim());
  const hasLeadEmail = Boolean(org?.safeguarding_lead_email && org.safeguarding_lead_email.trim());
  const hasMinorsDecision = typeof org?.works_with_minors === "boolean";
  return hasLeadName && hasLeadEmail && hasMinorsDecision;
}

// The five editable concepts, mapped to their terminology keys.
const TERMINOLOGY_ROWS: {
  label: string;
  singularKey: keyof Terminology;
  pluralKey: keyof Terminology;
}[] = [
  { label: "Who runs the session", singularKey: "coach_singular", pluralKey: "coach_plural" },
  { label: "Who takes part", singularKey: "player_singular", pluralKey: "player_plural" },
  { label: "Group of people", singularKey: "team_singular", pluralKey: "team_plural" },
  { label: "The activity itself", singularKey: "session_singular", pluralKey: "session_plural" },
  { label: "Where it happens", singularKey: "location_singular", pluralKey: "location_plural" },
];

export default function OrgSettings() {
  const { toast } = useToast();
  const { user } = useAuth();
  const orgId = user?.org_id ?? null;
  const refreshTerminology = useRefreshTerminology();
  const [org, setOrg] = useState<Organisation | null>(null);
  const [terminology, setTerminology] = useState<Terminology>(DEFAULT_TERMINOLOGY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Safeguarding section state. worksWithMinors is deliberately tri-state:
  // null means "not declared" (never treat that as false), true/false means
  // an admin actively made that choice.
  const [leadName, setLeadName] = useState("");
  const [leadEmail, setLeadEmail] = useState("");
  const [worksWithMinors, setWorksWithMinors] = useState<boolean | null>(null);
  const [savingSafeguarding, setSavingSafeguarding] = useState(false);

  const safeguardingConfigured = isSafeguardingFullyConfigured(org);

  useEffect(() => {
    if (!orgId) {
      setLoading(false);
      return;
    }
    const load = async () => {
      try {
        setLoading(true);
        const [orgRes, termRes] = await Promise.all([
          organisationsAPI.getById(orgId),
          organisationsAPI.getTerminology(orgId),
        ]);
        setOrg(orgRes.organisation);
        // Saved terminology takes priority; any missing key falls back to
        // this org's type-based default rather than the sports default.
        setTerminology({
          ...getDefaultTerminology(orgRes.organisation.type),
          ...termRes.terminology,
        });
        setLeadName(orgRes.organisation.safeguarding_lead_name ?? "");
        setLeadEmail(orgRes.organisation.safeguarding_lead_email ?? "");
        setWorksWithMinors(
          typeof orgRes.organisation.works_with_minors === "boolean"
            ? orgRes.organisation.works_with_minors
            : null
        );
      } catch (err) {
        toast({
          title: "Failed to load settings",
          description: "Could not load organisation settings. Please try again.",
          variant: "destructive",
        });
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [orgId, toast]);

  const handleChange = (key: keyof Terminology, value: string) => {
    setTerminology((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    if (!orgId) return;
    try {
      setSaving(true);
      await organisationsAPI.update(orgId, { terminology });
      // Refresh the shared terminology so the sidebar and page titles update
      // immediately without a page reload.
      await refreshTerminology();
      toast({
        title: "Settings saved",
        description: "Your terminology changes have been saved.",
      });
    } catch (err) {
      toast({
        title: "Save failed",
        description: "Could not save your changes. Please try again.",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleSaveSafeguarding = async () => {
    if (!orgId) return;
    try {
      setSavingSafeguarding(true);
      const trimmedName = leadName.trim();
      const trimmedEmail = leadEmail.trim();
      const updated = await organisationsAPI.update(orgId, {
        safeguarding_lead_name: trimmedName || null,
        safeguarding_lead_email: trimmedEmail || null,
        works_with_minors: worksWithMinors,
      });
      setOrg(updated.organisation);
      toast({
        title: "Safeguarding settings saved",
        description: "Your safeguarding configuration has been updated.",
      });
    } catch (err: any) {
      toast({
        title: "Save failed",
        description: err?.message || "Could not save your safeguarding settings. Please try again.",
        variant: "destructive",
      });
    } finally {
      setSavingSafeguarding(false);
    }
  };

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-foreground">Organisation Settings</h1>
          <p className="text-muted-foreground">
            Manage your organisation details and customise terminology
          </p>
        </div>

        {!orgId ? (
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              No organisation configured
            </CardContent>
          </Card>
        ) : loading ? (
          <div className="flex items-center justify-center py-16 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading settings...
          </div>
        ) : (
          <>
            {/* Section 1: Organisation Details */}
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Building2 className="w-5 h-5 text-primary" />
                  <CardTitle>Organisation Details</CardTitle>
                </div>
                <CardDescription>Your organisation's name and type</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label className="text-muted-foreground">Name</Label>
                  <p className="text-sm font-medium text-foreground">{org?.name ?? "—"}</p>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-muted-foreground">Type</Label>
                  <p className="text-sm font-medium text-foreground">
                    {org?.type ? ORG_TYPE_LABELS[org.type] ?? org.type : "—"}
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* Section 2: Terminology */}
            <Card>
              <CardHeader>
                <CardTitle>Terminology</CardTitle>
                <CardDescription>
                  Customise what your organisation calls each concept. These labels appear
                  throughout the app.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Column headers */}
                <div className="hidden sm:grid grid-cols-[120px_1fr_1fr] gap-4 px-1">
                  <span className="text-xs font-medium text-muted-foreground">Concept</span>
                  <span className="text-xs font-medium text-muted-foreground">Singular</span>
                  <span className="text-xs font-medium text-muted-foreground">Plural</span>
                </div>

                {TERMINOLOGY_ROWS.map((row) => (
                  <div
                    key={row.label}
                    className="grid grid-cols-1 sm:grid-cols-[120px_1fr_1fr] gap-4 items-center"
                  >
                    <Label className="text-sm font-medium text-foreground">{row.label}</Label>
                    <Input
                      aria-label={`${row.label} singular`}
                      value={terminology[row.singularKey]}
                      onChange={(e) => handleChange(row.singularKey, e.target.value)}
                      disabled={saving}
                    />
                    <Input
                      aria-label={`${row.label} plural`}
                      value={terminology[row.pluralKey]}
                      onChange={(e) => handleChange(row.pluralKey, e.target.value)}
                      disabled={saving}
                    />
                  </div>
                ))}

                <div className="flex justify-end pt-2">
                  <Button onClick={handleSave} disabled={saving} className="gap-2">
                    {saving ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Save className="w-4 h-4" />
                    )}
                    Save changes
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Section 3: Safeguarding */}
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="w-5 h-5 text-primary" />
                    <CardTitle>Safeguarding</CardTitle>
                  </div>
                  {safeguardingConfigured ? (
                    <Badge variant="outline">Configured</Badge>
                  ) : (
                    <Badge variant="outline" className="gap-1.5 border-amber-500 text-amber-600 dark:text-amber-400">
                      <AlertTriangle className="w-3.5 h-3.5" />
                      Not configured
                    </Badge>
                  )}
                </div>
                <CardDescription>
                  Who to contact for safeguarding concerns, and whether this organisation works
                  with minors.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="safeguarding-lead-name">Safeguarding lead name</Label>
                    <Input
                      id="safeguarding-lead-name"
                      value={leadName}
                      onChange={(e) => setLeadName(e.target.value)}
                      placeholder="e.g. Jane Doe"
                      disabled={savingSafeguarding}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="safeguarding-lead-email">Safeguarding lead email</Label>
                    <Input
                      id="safeguarding-lead-email"
                      type="email"
                      value={leadEmail}
                      onChange={(e) => setLeadEmail(e.target.value)}
                      placeholder="e.g. jane@example.com"
                      disabled={savingSafeguarding}
                    />
                  </div>
                </div>

                <div className="space-y-1.5 sm:max-w-xs">
                  <Label htmlFor="works-with-minors">Does this organisation work with minors?</Label>
                  <Select
                    value={worksWithMinors === null ? undefined : String(worksWithMinors)}
                    onValueChange={(v) => setWorksWithMinors(v === "true")}
                    disabled={savingSafeguarding}
                  >
                    <SelectTrigger id="works-with-minors" aria-label="Does this organisation work with minors?">
                      <SelectValue placeholder="Select an option" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="true">Yes</SelectItem>
                      <SelectItem value="false">No</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex justify-end pt-2">
                  <Button onClick={handleSaveSafeguarding} disabled={savingSafeguarding} className="gap-2">
                    {savingSafeguarding ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Save className="w-4 h-4" />
                    )}
                    Save changes
                  </Button>
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </MainLayout>
  );
}
