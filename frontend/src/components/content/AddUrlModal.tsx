import { useState, useEffect } from "react";
import { Link, Loader2 } from "lucide-react";
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
import { contentAPI } from "@/services/api";

export interface UrlItem {
  id: string | number;
  url: string;
  title: string;
  description: string;
  instructions: string;
}

interface AddUrlModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd?: (item: UrlItem) => void;
  editItem?: UrlItem | null;
  onSave?: (item: UrlItem) => void;
}

export function AddUrlModal({ open, onOpenChange, onAdd, editItem, onSave }: AddUrlModalProps) {
  const { toast } = useToast();
  const [saving, setSaving] = useState(false);
  const [formData, setFormData] = useState({
    url: "",
    title: "",
    description: "",
    instructions: "",
  });

  // Reset form when editItem changes or modal opens
  useEffect(() => {
    if (editItem) {
      setFormData({
        url: editItem.url,
        title: editItem.title,
        description: editItem.description,
        instructions: editItem.instructions,
      });
    } else {
      setFormData({ url: "", title: "", description: "", instructions: "" });
    }
  }, [editItem, open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editItem) {
        await contentAPI.updateUrl(String(editItem.id), formData);
        onSave?.({ ...editItem, ...formData });
        toast({ title: "URL updated" });
      } else {
        const res = await contentAPI.createUrl(formData);
        const newItem: UrlItem = {
          id: res.url?.id || Date.now(),
          ...formData,
        };
        onAdd?.(newItem);
        toast({ title: "URL added" });
      }
      onOpenChange(false);
      setFormData({ url: "", title: "", description: "", instructions: "" });
    } catch (err: any) {
      toast({
        title: editItem ? "Update failed" : "Add failed",
        description: err.message || "Failed to save URL.",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
              <Link className="w-5 h-5 text-primary" />
            </div>
            <div>
              <DialogTitle className="text-xl">{editItem ? "Edit URL" : "Add URL"}</DialogTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Add a URL the AI assistant can share with coaches
              </p>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          <div className="space-y-2">
            <Label htmlFor="url-title">Title</Label>
            <Input
              id="url-title"
              placeholder="e.g. First Aid Training Video"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="url">URL</Label>
            <Input
              id="url"
              type="url"
              placeholder="https://..."
              value={formData.url}
              onChange={(e) => setFormData({ ...formData, url: e.target.value })}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="url-description">Description</Label>
            <Textarea
              id="url-description"
              placeholder="What is this link about?"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              rows={2}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="url-instructions">AI Instructions</Label>
            <Textarea
              id="url-instructions"
              placeholder="When should the AI share this URL? e.g. 'Share when a coach asks about first aid procedures'"
              value={formData.instructions}
              onChange={(e) => setFormData({ ...formData, instructions: e.target.value })}
              rows={3}
            />
            <p className="text-xs text-muted-foreground">
              Tell the AI when and how to share this URL with coaches
            </p>
          </div>

          <div className="flex gap-3 pt-4">
            <Button type="submit" className="flex-1" disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Saving...
                </>
              ) : editItem ? (
                "Save Changes"
              ) : (
                "Add URL"
              )}
            </Button>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
