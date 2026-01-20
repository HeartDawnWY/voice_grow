import * as React from "react";
import { cn } from "../../lib/utils";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "success" | "warning" | "destructive";
}

const Badge: React.FC<BadgeProps> = ({
  className,
  variant = "default",
  ...props
}) => {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        {
          "bg-primary-100 text-primary-800": variant === "default",
          "bg-gray-100 text-gray-800": variant === "secondary",
          "bg-green-100 text-green-800": variant === "success",
          "bg-yellow-100 text-yellow-800": variant === "warning",
          "bg-red-100 text-red-800": variant === "destructive",
        },
        className
      )}
      {...props}
    />
  );
};

export { Badge };
