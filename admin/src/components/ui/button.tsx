import * as React from "react";
import { cn } from "../../lib/utils";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    return (
      <button
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500/20 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
          {
            // Default: Orange gradient
            "bg-gradient-to-r from-orange-500 to-orange-600 text-white shadow-md shadow-orange-500/25 hover:shadow-lg hover:shadow-orange-500/30 hover:-translate-y-0.5 active:translate-y-0":
              variant === "default",
            // Destructive: Red gradient
            "bg-gradient-to-r from-red-500 to-red-600 text-white shadow-md shadow-red-500/25 hover:shadow-lg hover:shadow-red-500/30 hover:-translate-y-0.5":
              variant === "destructive",
            // Outline: Border with hover fill
            "border-2 border-stone-200 bg-white text-gray-700 hover:border-orange-300 hover:bg-orange-50 hover:text-orange-600":
              variant === "outline",
            // Secondary: Soft background
            "bg-stone-100 text-gray-700 hover:bg-stone-200":
              variant === "secondary",
            // Ghost: No background
            "text-gray-600 hover:bg-stone-100 hover:text-gray-900":
              variant === "ghost",
            // Link: Underline
            "text-orange-600 underline-offset-4 hover:underline":
              variant === "link",
          },
          {
            "h-10 px-5 py-2": size === "default",
            "h-8 rounded-lg px-3 text-xs": size === "sm",
            "h-12 rounded-xl px-8 text-base": size === "lg",
            "h-10 w-10": size === "icon",
          },
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
