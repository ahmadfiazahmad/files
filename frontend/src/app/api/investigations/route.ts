import { NextResponse } from "next/server";

import { listExternalInvestigations, listInvestigations } from "@/server/repositories/investigations";
import { backendEnabled } from "@/server/backendClient";
import { getStudentKey } from "@/server/session";

export const dynamic = "force-dynamic";

export async function GET() {
  const studentKey = await getStudentKey();
  const items = backendEnabled()
    ? await listExternalInvestigations(studentKey)
    : await listInvestigations(studentKey);
  return NextResponse.json({ investigations: items });
}
