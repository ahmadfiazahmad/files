import type { Metadata } from "next";

import { ChatView } from "@/components/Chat/ChatView";
import { getInvestigation } from "@/server/repositories/investigations";
import { backendEnabled, backendGetInvestigation } from "@/server/backendClient";
import { adaptBackendInvestigation } from "@/server/backendAdapter";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Investigation — Study Abroad Safety Assistant",
  description:
    "Describe the university, program, scholarship, consultant or payment request you have been offered and find out what needs to be verified.",
};

export default async function InvestigatePage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  const { id } = await searchParams;
  let investigation = null;
  const mode = backendEnabled() ? "external_backend" : "internal_engine" as const;
  if (id) {
    if (backendEnabled()) {
      try {
        investigation = adaptBackendInvestigation(await backendGetInvestigation(id));
      } catch {
        investigation = null;
      }
    } else {
      investigation = await getInvestigation(Number(id)).catch(() => null);
    }
  }
  return <ChatView initialInvestigation={investigation} initialMode={mode} />;
}
