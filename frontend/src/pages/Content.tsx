import { useState, useEffect } from "react";
import { Plus, Search, FileText, Upload, Tag, Languages, Pencil, Trash2, Filter, Link, ExternalLink, FileSpreadsheet, Type, Loader2 } from "lucide-react";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MainLayout } from "@/components/layout/MainLayout";
import { AddContentModal, type ContentItem } from "@/components/content/AddContentModal";
import { EditContentModal } from "@/components/content/EditContentModal";
import { AddUrlModal, type UrlItem } from "@/components/content/AddUrlModal";
import { useToast } from "@/hooks/use-toast";
import { contentAPI } from "@/services/api";

const typeFilters = ["All", "Text", "PDF", "CSV", "Excel", "Document"];

const typeIcons: Record<string, React.ElementType> = {
  Text: Type,
  PDF: FileText,
  CSV: FileSpreadsheet,
  Excel: FileSpreadsheet,
  Document: FileText,
};

export default function Content() {
  const { toast } = useToast();
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("All");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [contentItems, setContentItems] = useState<ContentItem[]>([]);
  const [editItem, setEditItem] = useState<ContentItem | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);

  // URL state
  const [urls, setUrls] = useState<UrlItem[]>([]);
  const [isAddUrlOpen, setIsAddUrlOpen] = useState(false);
  const [editUrl, setEditUrl] = useState<UrlItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ type: "content" | "url"; id: number } | null>(null);

  // Loading state
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);

  // Fetch content and URLs on mount
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [contentRes, urlsRes] = await Promise.all([
          contentAPI.getAll(),
          contentAPI.getAllUrls(),
        ]);

        if (contentRes.success && contentRes.content) {
          setContentItems(
            contentRes.content.map((c: any) => ({
              id: c.id,
              title: c.title,
              type: c.type || "Text",
              topic: c.topic || "",
              language: c.language || "English",
              date: c.created_at
                ? new Date(c.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                : "",
              content: c.content_text || c.content || "",
              fileName: c.file_name || "",
            }))
          );
        }

        if (urlsRes.success && urlsRes.urls) {
          setUrls(
            urlsRes.urls.map((u: any) => ({
              id: u.id,
              url: u.url,
              title: u.title,
              description: u.description || "",
              instructions: u.instructions || "",
            }))
          );
        }
      } catch (err: any) {
        toast({
          title: "Error loading content",
          description: err.message || "Failed to load content.",
          variant: "destructive",
        });
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const filteredContent = contentItems.filter((item) => {
    const matchesSearch =
      item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.topic.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesType = typeFilter === "All" || item.type === typeFilter;
    return matchesSearch && matchesType;
  });

  const handleAddContent = async (item: ContentItem) => {
    // The modal already calls the API; just add to local state
    setContentItems((prev) => [item, ...prev]);
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      if (deleteTarget.type === "content") {
        await contentAPI.delete(String(deleteTarget.id));
        setContentItems((prev) => prev.filter((item) => item.id !== deleteTarget.id));
        toast({ title: "Content deleted" });
      } else {
        await contentAPI.deleteUrl(String(deleteTarget.id));
        setUrls((prev) => prev.filter((item) => item.id !== deleteTarget.id));
        toast({ title: "URL deleted" });
      }
    } catch (err: any) {
      toast({
        title: "Delete failed",
        description: err.message || "Failed to delete item.",
        variant: "destructive",
      });
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const handleEditContent = (item: ContentItem) => {
    setEditItem(item);
    setIsEditModalOpen(true);
  };

  const handleSaveEdit = async (updated: ContentItem) => {
    // The modal already calls the API; just update local state
    setContentItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
  };

  const handleAddUrl = async (item: UrlItem) => {
    // The modal already calls the API; just add to local state
    setUrls((prev) => [item, ...prev]);
  };

  const handleSaveUrl = async (updated: UrlItem) => {
    // The modal already calls the API; just update local state
    setUrls((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    setEditUrl(null);
  };




  const IconForType = (type: string) => typeIcons[type] || FileText;

  return (
    <MainLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="page-header">
          <div>
            <h1 className="page-title">Content</h1>
            <p className="page-subtitle">Manage learning and coaching content</p>
          </div>
          <Button className="gap-2" onClick={() => setIsAddModalOpen(true)}>
            <Upload className="w-4 h-4" />
            Upload Content
          </Button>
        </div>

        {/* Search + Filter */}
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search content by title or topic..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 bg-card"
            />
          </div>
          <div className="flex items-center gap-1 overflow-x-auto">
            <Filter className="w-4 h-4 text-muted-foreground mr-1 flex-shrink-0" />
            {typeFilters.map((type) => (
              <button
                key={type}
                onClick={() => setTypeFilter(type)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
                  typeFilter === type
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/80"
                }`}
              >
                {type}
              </button>
            ))}
          </div>
        </div>

        {/* Content list */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <>
            <div className="space-y-3">
              {filteredContent.map((item) => {
                const TypeIcon = IconForType(item.type);
                return (
                  <div
                    key={item.id}
                    className="bg-card rounded-xl border border-border p-4 shadow-card hover:shadow-card-hover transition-shadow"
                  >
                    <div className="flex items-start gap-4">
                      <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                        <TypeIcon className="w-6 h-6 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="font-semibold text-foreground">{item.title}</h3>
                        <div className="flex items-center gap-3 mt-2 flex-wrap">
                          <span className="text-xs bg-muted text-muted-foreground px-2 py-1 rounded">
                            {item.type}
                          </span>
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Tag className="w-3 h-3" />
                            {item.topic}
                          </div>
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Languages className="w-3 h-3" />
                            {item.language}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span className="text-sm text-muted-foreground hidden sm:block">{item.date}</span>
                        <Button variant="ghost" size="icon" onClick={() => handleEditContent(item)}>
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => setDeleteTarget({ type: "content", id: item.id })}>
                          <Trash2 className="w-4 h-4 text-destructive" />
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {filteredContent.length === 0 && (
              <div className="text-center py-12">
                <FileText className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
                <p className="text-muted-foreground">No content found</p>
              </div>
            )}
          </>
        )}

        {/* URL Resources Section */}
        <div className="pt-4 border-t border-border">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                <Link className="w-5 h-5" />
                URL Resources
              </h2>
              <p className="text-sm text-muted-foreground">
                URLs the AI assistant can share with coaches based on context
              </p>
            </div>
            <Button variant="outline" className="gap-2" onClick={() => { setEditUrl(null); setIsAddUrlOpen(true); }}>
              <Plus className="w-4 h-4" />
              Add URL
            </Button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-3">
              {urls.map((item) => (
                <div
                  key={item.id}
                  className="bg-card rounded-xl border border-border p-4 shadow-card"
                >
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-lg bg-accent/50 flex items-center justify-center flex-shrink-0">
                      <ExternalLink className="w-5 h-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-foreground">{item.title}</h3>
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-primary hover:underline break-all"
                      >
                        {item.url}
                      </a>
                      {item.description && (
                        <p className="text-sm text-muted-foreground mt-1">{item.description}</p>
                      )}
                      {item.instructions && (
                        <div className="mt-2 text-xs bg-muted/50 rounded-lg px-3 py-2 text-muted-foreground">
                          <span className="font-medium text-foreground">AI Instruction:</span> {item.instructions}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => { setEditUrl(item); setIsAddUrlOpen(true); }}
                      >
                        <Pencil className="w-4 h-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => setDeleteTarget({ type: "url", id: item.id })}>
                        <Trash2 className="w-4 h-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}

              {urls.length === 0 && (
                <div className="text-center py-8">
                  <Link className="w-10 h-10 text-muted-foreground/30 mx-auto mb-2" />
                  <p className="text-muted-foreground text-sm">No URLs added yet</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <AddContentModal open={isAddModalOpen} onOpenChange={setIsAddModalOpen} onAdd={handleAddContent} />
      <EditContentModal open={isEditModalOpen} onOpenChange={setIsEditModalOpen} item={editItem} onSave={handleSaveEdit} />
      <AddUrlModal
        open={isAddUrlOpen}
        onOpenChange={(open) => { setIsAddUrlOpen(open); if (!open) setEditUrl(null); }}
        onAdd={handleAddUrl}
        editItem={editUrl}
        onSave={handleSaveUrl}
      />
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete this {deleteTarget?.type === "url" ? "URL resource" : "content item"}. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90" disabled={deleting}>
              {deleting ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </MainLayout>
  );
}
