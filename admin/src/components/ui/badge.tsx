import * as React from "react";
import { cn } from "../../lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "success" | "warning" | "destructive" | "story" | "music" | "english";
}

const Badge: React.FC<BadgeProps> = ({
  className,
  variant = "default",
  ...props
}) => {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        {
          // Default: Orange
          "bg-orange-100 text-orange-700": variant === "default",
          // Secondary: Gray
          "bg-stone-100 text-stone-600": variant === "secondary",
          // Success: Green
          "bg-green-100 text-green-700": variant === "success",
          // Warning: Amber
          "bg-amber-100 text-amber-700": variant === "warning",
          // Destructive: Red
          "bg-red-100 text-red-700": variant === "destructive",
          // Story: Rose
          "bg-rose-100 text-rose-700": variant === "story",
          // Music: Violet
          "bg-violet-100 text-violet-700": variant === "music",
          // English: Emerald
          "bg-emerald-100 text-emerald-700": variant === "english",
        },
        className
      )}
      {...props}
    />
  );
};

export { Badge };
