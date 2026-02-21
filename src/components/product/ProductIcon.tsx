"use client";

import { useState } from "react";

const DEFAULT_ICON = "/icons/default-product.svg";

interface ProductIconProps {
  iconUrl?: string;
  name: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeMap = {
  sm: "w-8 h-8",
  md: "w-10 h-10",
  lg: "w-16 h-16",
} as const;

export function ProductIcon({ iconUrl, name, size = "md", className = "" }: ProductIconProps) {
  const [src, setSrc] = useState(iconUrl || DEFAULT_ICON);

  return (
    <img
      src={src}
      alt={name}
      className={`${sizeMap[size]} rounded-lg object-cover bg-muted shrink-0 ${className}`}
      onError={() => setSrc(DEFAULT_ICON)}
      loading="lazy"
    />
  );
}
