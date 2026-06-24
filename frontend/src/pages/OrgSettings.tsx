import { useState, useEffect } from "react";
import { MainLayout } from "@/components/layout/MainLayout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Building2, Loader2, Save } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { organisationsAPI } from "@/services/api";
import {
  DEFAULT_TERMINOLOGY,
  type Organisation,
  type OrganisationType,
  type Terminology,
} from "@/types/Organisation";

// TODO: replace with org_id from user session once auth is multi-tenant
const ORG_ID = "2I8r2Hb2q7pNgjDbcG8w";

const ORG_TYPE_LABELS: Record<OrganisationType, string> = {
  sports: "Sports",
  ngo: "NGO",
  events: "Events",
  corporate: "Corporate",
};

// The five editable concepts, mapped to their terminology keys.
const TERMINOLOGY_ROWS: {
  label: string;
  singularKey: keyof Terminology;
  pluralKey: keyof Terminology;
}[] = [
  { label: "Coach", singularKey: "coach_singular", pluralKey: "coach_plural" },
  { label: "Player", singularKey: "player_singular", pluralKey: "player_plural" },
  { label: "Team", singularKey: "team_singular", pluralKey: "team_plural" },
  { label: "Session", singularKey: "session_singular", pluralKey: "session_plural" },
  { label: "Location", singularKey: "location_singular", pluralKey: "location_plural" },
];

export default function OrgSettings() {
  const { toast } = useToast();
  const [org, setOrg] = useState<Organisation | null>(null);
  const [terminology, setTerminology] = useState<Terminology>(DEFAULT_TERMINOLOGY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        const [orgRes, termRes] = await Promise.all([
          organisationsAPI.getById(ORG_ID),
          organisationsAPI.getTerminology(ORG_ID),
        ]);
        setOrg(orgRes.organisation);
        setTerminology({ ...DEFAULT_TERMINOLOGY, ...termRes.terminology });
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
  }, [toast]);

  const handleChange = (key: keyof Terminology, value: string) => {
    setTerminology((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      await organisationsAPI.update(ORG_ID, { terminology });
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

        {loading ? (
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
          </>
        )}
      </div>
    </MainLayout>
  );
}
