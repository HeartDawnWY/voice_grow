import * as React from "react";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}

const Dialog: React.FC<DialogProps> = ({ open, onClose, children, className }) => {
  React.useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (open) {
      document.addEventListener("keydown", handleEscape);
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.removeEventListener("keydown", handleEscape);
      document.body.style.overflow = "unset";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="fixed inset-0 bg-black/50"
        onClick={onClose}
      />
      <div className={cn("relative z-50 w-full max-w-lg max-h-[90vh] overflow-auto bg-white rounded-lg shadow-lg", className)}>
        {children}
      </div>
    </div>
  );
};

interface DialogHeaderProps {
  children: React.ReactNode;
  onClose?: () => void;
  className?: string;
}

const DialogHeader: React.FC<DialogHeaderProps> = ({
  children,
  onClose,
  className,
}) => (
  <div
    className={cn(
      "flex items-center justify-between px-6 py-4 border-b",
      className
    )}
  >
    <h2 className="text-lg font-semibold">{children}</h2>
    {onClose && (
      <button
        onClick={onClose}
        className="rounded-full p-1 hover:bg-gray-100 transition-colors"
      >
        <X className="h-5 w-5" />
      </button>
    )}
  </div>
);

interface DialogContentProps {
  children: React.ReactNode;
  className?: string;
}

const DialogContent: React.FC<DialogContentProps> = ({
  children,
  className,
}) => <div className={cn("px-6 py-4", className)}>{children}</div>;

interface DialogFooterProps {
  children: React.ReactNode;
  className?: string;
}

const DialogFooter: React.FC<DialogFooterProps> = ({
  children,
  className,
}) => (
  <div
    className={cn(
      "flex items-center justify-end gap-2 px-6 py-4 border-t bg-gray-50",
      className
    )}
  >
    {children}
  </div>
);

export { Dialog, DialogHeader, DialogContent, DialogFooter };
