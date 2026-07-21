import { MessageSquare } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useUpdateComment } from "@/hooks/useUpdateComment";
import { cn } from "@/lib/utils";

interface CommentPopoverProps {
  forwardedTo: string;
  dateFileName: string;
  comment: string | null;
  tourAnchor?: string | undefined;
  /** `icon` (default) renders the hover-cluster icon button. `marginalia`
   *  renders the note text itself as an italic, muted, clickable line —
   *  only meaningful when `comment` is non-null. */
  variant?: "icon" | "marginalia" | undefined;
}

export function CommentPopover({
  forwardedTo,
  dateFileName,
  comment,
  tourAnchor,
  variant = "icon",
}: CommentPopoverProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(comment ?? "");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mutation = useUpdateComment();

  const hasComment = !!comment;
  const isDirty = draft !== (comment ?? "");

  useEffect(() => {
    if (open) {
      setDraft(comment ?? "");
      // Auto-focus textarea after popover animation
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
  }, [open, comment]);

  const handleSave = () => {
    const value = draft.trim() || null;
    mutation.mutate({ forwardedTo, dateFileName, comment: value });
    setOpen(false);
  };

  const handleClear = () => {
    mutation.mutate({ forwardedTo, dateFileName, comment: null });
    setOpen(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSave();
    }
  };

  const trigger =
    variant === "marginalia" ? (
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={hasComment ? `Edit note: ${comment}` : "Add note"}
          data-tour={tourAnchor}
          className="text-left text-xs italic text-muted-foreground hover:text-foreground/80 transition-colors line-clamp-2 cursor-pointer rounded-sm px-0.5 -mx-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="text-muted-foreground/50">&ldquo;</span>
          {comment}
          <span className="text-muted-foreground/50">&rdquo;</span>
        </button>
      </PopoverTrigger>
    ) : (
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <button
              aria-label={hasComment ? "Edit note" : "Add note"}
              data-tour={tourAnchor}
              className={cn(
                // Rest color meets the 3:1 non-text floor; has-comment state is
                // carried by the filled glyph below, not by a lighter tint.
                "rounded p-0.5 text-muted-foreground transition-colors hover:text-brand hover:bg-brand/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
              )}
            >
              <MessageSquare className="h-4 w-4" fill={hasComment ? "currentColor" : "none"} />
            </button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{hasComment ? "Edit note" : "Add note"}</TooltipContent>
      </Tooltip>
    );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {trigger}
      <PopoverContent className="w-72 p-3" align="start">
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          maxLength={500}
          placeholder="Add a note..."
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 resize-none"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">{draft.length}/500</span>
          <div className="flex gap-1.5">
            {hasComment && (
              <Button variant="ghost" size="sm" onClick={handleClear}>
                Clear
              </Button>
            )}
            <Button size="sm" onClick={handleSave} disabled={!isDirty}>
              Save
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
