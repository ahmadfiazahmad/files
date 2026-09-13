import { NextResponse } from "next/server";

import { runContextUpdate } from "@/server/engine/run";
import { backendEnabled, backendUpdateContext } from "@/server/backendClient";
import { adaptAssistantMessage, adaptContext, adaptStudentMessage } from "@/server/backendAdapter";
import { getStudentKey } from "@/server/session";
import { ensureExternalInvestigation, appendMessage, syncExternalInvestigation } from "@/server/repositories/investigations";

export const dynamic = "force-dynamic";

type ContextField =
  | "country"
  | "degree_level"
  | "university"
  | "program"
  | "scholarship"
  | "agent"
  | "funding_type"
  | "payment_amount_pkr";

interface ContextBody {
  updates?: Partial<Record<ContextField, string | number | null>>;
  note?: string;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    const body = (await request.json().catch(() => ({}))) as ContextBody;
    const updates = body.updates ?? {};
    if (Object.keys(updates).length === 0) {
      return NextResponse.json({ error: "No updates supplied" }, { status: 400 });
    }

    if (backendEnabled()) {
      const result = await backendUpdateContext(id, updates as Record<string, string | number | null>, body.note);
      const studentText = `[Investigation profile updated] ${Object.entries(updates)
        .map(([key, value]) => `${key}: ${value ?? "removed"}`)
        .join(" · ")}${body.note ? ` — ${body.note}` : ""}`;
      const studentMessage = adaptStudentMessage(studentText);
      const assistantMessage = adaptAssistantMessage(result.assistant_message, null);
      const studentKey = await getStudentKey();
      const mirror = await ensureExternalInvestigation({
        studentKey,
        externalId: id,
        context: adaptContext(result.structured_case),
      });
      await appendMessage({ investigationId: mirror.id, role: "student", text: studentText });
      await appendMessage({ investigationId: mirror.id, role: "assistant", text: result.assistant_message });
      await syncExternalInvestigation({
        externalId: id,
        studentKey,
        context: adaptContext(result.structured_case),
        status: result.ready_for_verification ? "ready_for_verification" : "in_progress",
      });
      return NextResponse.json({
        studentMessage,
        assistantMessage,
        result: null,
        mode: "external_backend",
      });
    }

    const investigationId = Number(id);
    if (!Number.isFinite(investigationId)) {
      return NextResponse.json({ error: "Invalid investigation id" }, { status: 400 });
    }

    const turn = await runContextUpdate({ investigationId, updates, note: body.note });
    return NextResponse.json({ ...turn, mode: "internal_engine" });
  } catch (error) {
    console.error("context update failed", error);
    return NextResponse.json({ error: "Could not update the investigation profile" }, { status: 500 });
  }
}
