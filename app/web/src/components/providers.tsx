"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2_000 } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delay={200}>{children}</TooltipProvider>
      <Toaster position="bottom-right" />
    </QueryClientProvider>
  );
}
