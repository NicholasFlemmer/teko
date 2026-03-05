import { useState } from "react";
import { Upload, FileText, FileSpreadsheet, File, Type, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { contentAPI, uploadsAPI } from "@/services/api";

interface AddContentModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd?: (content: ContentItem) => void;
}

export interface ContentItem {
  id: string | number;
  title: string;
  type: string;
  topic: string;
  language: string;
  date: string;
  content?: string;
  fileName?: string;
}

const contentTypes = [
  { id: "text", label: "Text", icon: Type, description: "Type or paste text", accept: "" },
  { id: "PDF", label: "PDF", icon: File, description: "Upload PDF document", accept: ".pdf" },
  { id: "CSV", label: "CSV", icon: FileSpreadsheet, description: "Upload CSV file", accept: ".csv" },
  { id: "Excel", label: "Excel", icon: FileSpreadsheet, description: "Upload Excel file", accept: ".xlsx,.xls" },
  { id: "Document", label: "Other", icon: FileText, description: "Any other file", accept: "*" },
];

export function AddContentModal({ open, onOpenChange, onAdd }: AddContentModalProps) {
  const { toast } = useToast();
  const [saving, setSaving] = useState(false);
  const [formData, setFormData] = useState({
    title: "",
    type: "text",
    topic: "",
    language: "English",
    content: "",
    file: null as File | null,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const apiData: any = {
        title: formData.title,
        type: formData.type === "text" ? "Text" : formData.type,
        topic: formData.topic,
        language: formData.language,
      };

      if (formData.type === "text") {
        apiData.content_text = formData.content;
      }

      // Upload file to Firebase Storage first, then create content record
      if (formData.file) {
        const uploadRes = await uploadsAPI.upload(formData.file, 'content');
        apiData.file_name = uploadRes.file.file_name;
        apiData.file_url = uploadRes.file.public_url;
        apiData.file_path = uploadRes.file.file_path;
      }

      const res = await contentAPI.create(apiData);

      const newItem: ContentItem = {
        id: res.content?.id || Date.now(),
        title: formData.title,
        type: formData.type === "text" ? "Text" : formData.type,
        topic: formData.topic,
        language: formData.language,
        date: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
        content: formData.content,
        fileName: formData.file?.name,
      };
      onAdd?.(newItem);
      onOpenChange(false);
      setFormData({ title: "", type: "text", topic: "", language: "English", content: "", file: null });
      toast({ title: "Content uploaded" });
    } catch (err: any) {
      toast({
        title: "Upload failed",
        description: err.message || "Failed to upload content.",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    setFormData({ ...formData, file, title: formData.title || file?.name?.replace(/\.[^.]+$/, "") || "" });
  };

  const selectedType = contentTypes.find((t) => t.id === formData.type);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
              <Upload className="w-5 h-5 text-primary" />
            </div>
            <div>
              <DialogTitle className="text-xl">Upload Content</DialogTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Add learning material for coaches
              </p>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          <div className="space-y-2">
            <Label>Content Type</Label>
            <div className="grid grid-cols-5 gap-2">
              {contentTypes.map((type) => (
                <button
                  key={type.id}
                  type="button"
                  onClick={() => setFormData({ ...formData, type: type.id, file: null })}
                  className={`p-2 rounded-lg border text-center transition-all ${
                    formData.type === type.id
                      ? "border-primary bg-primary/5 text-primary"
                      : "border-border hover:border-muted-foreground/30"
                  }`}
                >
                  <type.icon className="w-4 h-4 mx-auto mb-1" />
                  <span className="text-xs font-medium">{type.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              placeholder="e.g. Warm-up Exercises Guide"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="topic">Topic</Label>
              <Input
                id="topic"
                placeholder="e.g. Training"
                value={formData.topic}
                onChange={(e) => setFormData({ ...formData, topic: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="language">Language</Label>
              <Input
                id="language"
                placeholder="e.g. English"
                value={formData.language}
                onChange={(e) => setFormData({ ...formData, language: e.target.value })}
              />
            </div>
          </div>

          {formData.type === "text" ? (
            <div className="space-y-2">
              <Label htmlFor="content">Content</Label>
              <Textarea
                id="content"
                placeholder="Type or paste your content here..."
                value={formData.content}
                onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                rows={6}
              />
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="file">Upload File</Label>
              <div className="border-2 border-dashed border-border rounded-lg p-6 text-center hover:border-muted-foreground/50 transition-colors">
                <input
                  id="file"
                  type="file"
                  accept={selectedType?.accept}
                  onChange={handleFileChange}
                  className="hidden"
                />
                <label htmlFor="file" className="cursor-pointer">
                  <Upload className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                  {formData.file ? (
                    <p className="text-sm text-foreground font-medium">{formData.file.name}</p>
                  ) : (
                    <>
                      <p className="text-sm text-foreground font-medium">
                        Click to upload {selectedType?.label} file
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {selectedType?.description}
                      </p>
                    </>
                  )}
                </label>
              </div>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            This content will be available to the WhatsApp coaching assistant
          </p>

          <div className="flex gap-3 pt-4">
            <Button type="submit" className="flex-1" disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Uploading...
                </>
              ) : (
                "Upload Content"
              )}
            </Button>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
              Cancel
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
