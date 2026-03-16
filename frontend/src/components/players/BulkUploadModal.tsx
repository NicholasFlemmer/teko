import { useState, useEffect, useRef } from "react";
import { Upload, FileSpreadsheet, CheckCircle2, AlertCircle, Loader2, X, Download } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { playersAPI, teamsAPI } from "@/services/api";

interface BulkUploadModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPlayersAdded?: () => void;
}

type UploadState = "select" | "uploading" | "done";

export function BulkUploadModal({ open, onOpenChange, onPlayersAdded }: BulkUploadModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string[][]>([]);
  const [teams, setTeams] = useState<any[]>([]);
  const [selectedTeams, setSelectedTeams] = useState<string[]>([]);
  const [state, setState] = useState<UploadState>("select");
  const [result, setResult] = useState<{ created_count: number; error_count: number; errors: { row: number; error: string }[]; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setFile(null);
      setPreview([]);
      setSelectedTeams([]);
      setState("select");
      setResult(null);
      setError(null);
      teamsAPI.getAll().then(res => setTeams(res.teams || [])).catch(console.error);
    }
  }, [open]);

  const handleFile = (f: File | null) => {
    if (!f) return;
    setFile(f);
    setError(null);

    // Parse preview (first 6 rows)
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (!text) return;
      const lines = text.split(/\r?\n/).filter(l => l.trim());
      const rows = lines.slice(0, 6).map(line => {
        // Simple CSV parse (handles quoted fields)
        const result: string[] = [];
        let current = "";
        let inQuotes = false;
        for (const ch of line) {
          if (ch === '"') { inQuotes = !inQuotes; continue; }
          if (ch === ',' && !inQuotes) { result.push(current.trim()); current = ""; continue; }
          current += ch;
        }
        result.push(current.trim());
        return result;
      });
      setPreview(rows);
    };
    reader.readAsText(f);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f && f.name.toLowerCase().endsWith('.csv')) {
      handleFile(f);
    } else {
      setError("Please upload a CSV file");
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setState("uploading");
    setError(null);
    try {
      const res = await playersAPI.bulkUpload(file, selectedTeams);
      setResult(res);
      setState("done");
      if (res.created_count > 0) {
        onPlayersAdded?.();
      }
    } catch (err: any) {
      setError(err.message || "Upload failed");
      setState("select");
    }
  };

  const handleTeamToggle = (teamId: string) => {
    setSelectedTeams(prev =>
      prev.includes(teamId) ? prev.filter(id => id !== teamId) : [...prev, teamId]
    );
  };

  const downloadTemplate = () => {
    const csv = "First Name,Last Name,Date of Birth,Guardian Name,Guardian Phone,Guardian Email,Notes\nThabo,Mokoena,2012-05-15,Nomsa Mokoena,+27821234567,nomsa@email.com,\n";
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "players_template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[580px] max-h-[90vh] p-0">
        <DialogHeader className="px-6 pt-6 pb-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
              <Upload className="w-5 h-5 text-primary" />
            </div>
            <div>
              <DialogTitle className="text-xl">Bulk Upload Players</DialogTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Import players from a CSV file
              </p>
            </div>
          </div>
        </DialogHeader>

        <ScrollArea className="max-h-[calc(90vh-120px)]">
          <div className="space-y-4 px-6 pb-6 pt-4">
            {error && (
              <div className="bg-destructive/10 text-destructive text-sm p-3 rounded-lg flex items-start gap-2">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                {error}
              </div>
            )}

            {state === "done" && result ? (
              <div className="space-y-4">
                <div className="flex items-center gap-3 p-4 rounded-lg bg-emerald-500/10">
                  <CheckCircle2 className="w-6 h-6 text-emerald-500" />
                  <div>
                    <p className="font-medium text-foreground">{result.message}</p>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      {result.created_count} player{result.created_count !== 1 ? "s" : ""} added
                    </p>
                  </div>
                </div>

                {result.errors.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-destructive">Errors ({result.error_count}):</p>
                    <div className="text-sm space-y-1 max-h-32 overflow-y-auto">
                      {result.errors.map((err, i) => (
                        <p key={i} className="text-muted-foreground">
                          Row {err.row}: {err.error}
                        </p>
                      ))}
                    </div>
                  </div>
                )}

                <Button className="w-full" onClick={() => onOpenChange(false)}>
                  Done
                </Button>
              </div>
            ) : (
              <>
                {/* File drop zone */}
                <div
                  className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
                    file ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground"
                  }`}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={handleDrop}
                  onClick={() => fileRef.current?.click()}
                  role="button"
                  tabIndex={0}
                >
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".csv"
                    className="hidden"
                    onChange={(e) => handleFile(e.target.files?.[0] || null)}
                  />
                  {file ? (
                    <div className="flex items-center justify-center gap-3">
                      <FileSpreadsheet className="w-8 h-8 text-primary" />
                      <div className="text-left">
                        <p className="font-medium text-foreground">{file.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {(file.size / 1024).toFixed(1)} KB
                          {preview.length > 1 && ` \u00B7 ${preview.length - 1} row${preview.length - 1 !== 1 ? "s" : ""} preview`}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="ml-2"
                        onClick={(e) => { e.stopPropagation(); setFile(null); setPreview([]); }}
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </div>
                  ) : (
                    <div>
                      <Upload className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                      <p className="text-sm text-muted-foreground">
                        Drag & drop a CSV file or <span className="text-primary font-medium">browse</span>
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Columns: First Name, Last Name, Date of Birth, Guardian Name, Phone, Email, Notes
                      </p>
                    </div>
                  )}
                </div>

                {/* Download template */}
                <Button variant="outline" size="sm" className="gap-2" onClick={downloadTemplate}>
                  <Download className="w-3.5 h-3.5" />
                  Download CSV Template
                </Button>

                {/* CSV Preview */}
                {preview.length > 0 && (
                  <div className="space-y-2">
                    <Label>Preview</Label>
                    <div className="border rounded-lg overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="bg-muted/50">
                            {preview[0].map((h, i) => (
                              <th key={i} className="px-2 py-1.5 text-left font-medium text-muted-foreground whitespace-nowrap">
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {preview.slice(1).map((row, ri) => (
                            <tr key={ri} className="border-t border-border">
                              {row.map((cell, ci) => (
                                <td key={ci} className="px-2 py-1.5 whitespace-nowrap text-foreground">
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Team assignment */}
                <div className="space-y-2">
                  <Label>Assign all players to teams (optional)</Label>
                  <div className="border border-border rounded-lg p-3 space-y-2 max-h-32 overflow-y-auto">
                    {teams.map((team) => (
                      <div key={team.id} className="flex items-center gap-2">
                        <Checkbox
                          id={`bulk-team-${team.id}`}
                          checked={selectedTeams.includes(team.id)}
                          onCheckedChange={() => handleTeamToggle(team.id)}
                        />
                        <label htmlFor={`bulk-team-${team.id}`} className="text-sm font-medium leading-none cursor-pointer flex-1">
                          {team.name}
                          <span className="text-xs text-muted-foreground ml-2">({team.age_group || "N/A"})</span>
                        </label>
                      </div>
                    ))}
                    {teams.length === 0 && (
                      <p className="text-sm text-muted-foreground">No teams available</p>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex gap-3 pt-2">
                  <Button
                    className="flex-1"
                    disabled={!file || state === "uploading"}
                    onClick={handleUpload}
                  >
                    {state === "uploading" ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                        Uploading...
                      </>
                    ) : (
                      <>
                        <Upload className="w-4 h-4 mr-2" />
                        Upload Players
                      </>
                    )}
                  </Button>
                  <Button variant="outline" onClick={() => onOpenChange(false)}>
                    Cancel
                  </Button>
                </div>
              </>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
