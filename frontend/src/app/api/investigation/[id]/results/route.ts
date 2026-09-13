import { NextResponse } from "next/server";

import type { Language } from "@/types";
import { backendEnabled, backendGetResults } from "@/server/backendClient";
import { adaptReport, adaptContext } from "@/server/backendAdapter";
import { getStudentKey } from "@/server/session";
import { syncExternalInvestigation } from "@/server/repositories/investigations";

export const dynamic = "force-dynamic";

/**
 * Lightweight polling endpoint for the backend's report
 * (backend/api/reports.py: GET /investigations/{id}/results), useful after
 * POST .../verify since that pipeline can take a while.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!backendEnabled()) {
    return NextResponse.json({ error: "No external backend is configured." }, { status: 501 });
  }
  try {
    const { id } = await params;
    const data = await backendGetResults(id);
    const language: Language = "roman_urdu";
    const result = data.report ? adaptReport(id, language, data.report, data.display_status) : null;
    await syncExternalInvestigation({ externalId: id, studentKey: await getStudentKey(), context: adaptContext(data.structured_case), status: data.status, result });
    return NextResponse.json({ status: data.status, result, mode: "external_backend" });
  } catch (error) {
    console.error("results lookup failed", error);
    return NextResponse.json({ error: "Investigation not found" }, { status: 404 });
  }
}
