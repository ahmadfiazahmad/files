import { NextResponse } from "next/server";

import type { InvestigationRecord, Language } from "@/types";
import { loadInvestigationPayload } from "@/server/engine/run";
import { backendEnabled, backendGetInvestigation } from "@/server/backendClient";
import { adaptBackendInvestigation } from "@/server/backendAdapter";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  if (backendEnabled()) {
    try {
      const data = await backendGetInvestigation(id);
      const investigation = adaptBackendInvestigation(data);
      return NextResponse.json({ investigation, mode: "external_backend" });
    } catch (error) {
      console.error("backend investigation lookup failed", error);
      return NextResponse.json({ error: "Investigation not found" }, { status: 404 });
    }
  }

  const numericId = Number(id);
  if (!Number.isFinite(numericId)) {
    return NextResponse.json({ error: "Invalid investigation id" }, { status: 400 });
  }
  const investigation = await loadInvestigationPayload(numericId);
  if (!investigation) {
    return NextResponse.json({ error: "Investigation not found" }, { status: 404 });
  }
  return NextResponse.json({ investigation, mode: "internal_engine" });
}
