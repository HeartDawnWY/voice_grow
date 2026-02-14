import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../../lib/utils";

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  options: { value: string; label: string }[];
  /** Compact inline style for filter bars */
  variant?: "default" | "filter";
}

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, label, error, options, id, variant = "default", value, ...props }, ref) => {
    const generatedId = React.useId();
    const selectId = id || generatedId;
    const isFilter = variant === "filter";
    const hasValue = value !== undefined && value !== "";

    return (
      <div className="w-full">
        {label && !isFilter && (
          <label
            htmlFor={selectId}
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            {label}
          </label>
        )}
        <div className="relative">
          <select
            id={selectId}
            value={value}
            className={cn(
              "appearance-none w-full bg-white text-sm transition-all duration-200 cursor-pointer pr-8",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500/20",
              "disabled:cursor-not-allowed disabled:opacity-50",
              isFilter
                ? cn(
                    "h-8 rounded-lg border pl-3 py-1",
                    hasValue
                      ? "border-orange-300 bg-orange-50 text-orange-700 font-medium"
                      : "border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50"
                  )
                : cn(
                    "h-9 rounded-lg border border-gray-200 px-3 py-1 shadow-sm",
                    "hover:border-gray-300",
                    "focus-visible:border-orange-400 focus-visible:ring-orange-500/20"
                  ),
              error && "border-red-500 focus-visible:ring-red-500/20",
              className
            )}
            ref={ref}
            {...props}
          >
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {isFilter && option.value === "" && label ? `${label}: ${option.label}` : option.label}
              </option>
            ))}
          </select>
          <ChevronDown
            className={cn(
              "absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none transition-colors",
              isFilter ? "h-3.5 w-3.5" : "h-4 w-4",
              isFilter && hasValue ? "text-orange-500" : "text-gray-400"
            )}
          />
        </div>
        {error && (
          <p className="mt-1 text-sm text-red-500">{error}</p>
        )}
      </div>
    );
  }
);
Select.displayName = "Select";

export { Select };
